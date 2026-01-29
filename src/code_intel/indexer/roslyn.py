"""Roslyn-based semantic indexer for C# code.

This module provides a semantic indexer that uses OmniSharp's Roslyn-based
analysis to build comprehensive call graphs that capture:
- Direct method calls
- Delegate invocations
- Event handlers
- Interface dispatch
- Virtual method calls

Unlike Tree-sitter parsing which only captures syntactic relationships,
this indexer understands the full semantic context of C# code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from code_intel.graph.schema import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)
from code_intel.graph.storage import GraphStorage
from code_intel.lsp.omnisharp import (
    OmniSharpError,
    OmniSharpServer,
)
from code_intel.lsp.protocol import CodeElement

logger = logging.getLogger(__name__)


@dataclass
class RoslynIndexResult:
    """Result of a Roslyn-based indexing operation."""

    files_indexed: int = 0
    """Number of files successfully indexed."""

    files_failed: int = 0
    """Number of files that failed to index."""

    symbols_indexed: int = 0
    """Total number of symbols (nodes) indexed."""

    usages_indexed: int = 0
    """Total number of usages (edges) indexed."""

    errors: list[str] = field(default_factory=list)
    """List of error messages."""


# Type alias for progress callback
RoslynProgressCallback = Callable[[int, int, str], None]
"""Callback for progress updates: (current, total, message)."""


class RoslynIndexer:
    """Roslyn-based semantic indexer for C# solutions.

    This indexer uses OmniSharp to perform semantic analysis of C# code,
    producing comprehensive call graphs that include indirect calls through
    delegates, events, and interface dispatch.

    Usage:
        indexer = RoslynIndexer("/path/to/database.db")

        # Index a solution
        result = indexer.index_solution(
            "/path/to/solution.sln",
            progress_callback=lambda cur, total, msg: print(f"{cur}/{total}: {msg}")
        )

        print(f"Indexed {result.symbols_indexed} symbols")
        print(f"Found {result.usages_indexed} usages")

    The indexer:
    1. Starts an OmniSharp server for the solution
    2. Queries /v2/codestructure for each file to get symbols
    3. Queries /findusages for each symbol to get relationships
    4. Stores nodes and edges in the SQLite graph
    5. Shuts down OmniSharp when complete
    """

    # Map OmniSharp symbol kinds to NodeKind
    SYMBOL_KIND_MAP = {
        # Types
        "class": NodeKind.CLASS,
        "struct": NodeKind.CLASS,
        "interface": NodeKind.INTERFACE,
        "enum": NodeKind.ENUM,
        "delegate": NodeKind.CLASS,  # Treat delegates as classes
        "record": NodeKind.CLASS,
        # Members
        "method": NodeKind.METHOD,
        "constructor": NodeKind.METHOD,
        "destructor": NodeKind.METHOD,
        "operator": NodeKind.METHOD,
        "indexer": NodeKind.METHOD,
        "property": NodeKind.PROPERTY,
        "field": NodeKind.VARIABLE,
        "event": NodeKind.VARIABLE,
        "constant": NodeKind.CONSTANT,
        "enummember": NodeKind.ENUM_MEMBER,
        # Namespace
        "namespace": NodeKind.MODULE,
        # Unknown
        "unknown": NodeKind.VARIABLE,
    }

    def __init__(
        self,
        db_path: Path | str | None = None,
        omnisharp_path: str | Path | None = None,
        timeout: float = 60.0,
    ):
        """Initialise the Roslyn indexer.

        Args:
            db_path: Path to the SQLite database file. If None, uses
                     an in-memory database (useful for testing).
            omnisharp_path: Path to OmniSharp executable. If None, searches
                           common installation paths.
            timeout: Default timeout for OmniSharp requests in seconds.
        """
        self._storage = GraphStorage(db_path)
        self._omnisharp_path = omnisharp_path
        self._timeout = timeout

    def index_solution(
        self,
        solution_path: Path | str,
        *,
        force: bool = False,
        progress_callback: RoslynProgressCallback | None = None,
    ) -> RoslynIndexResult:
        """Index a C# solution using OmniSharp.

        Args:
            solution_path: Path to .sln file or directory containing .csproj.
            force: If True, re-index even if already indexed (clears existing data).
            progress_callback: Optional callback for progress updates.
                              Called with (current, total, message).

        Returns:
            RoslynIndexResult with indexing statistics.
        """
        solution_path = Path(solution_path).resolve()
        repo_path = str(solution_path.parent)

        result = RoslynIndexResult()

        # Clear existing data if force re-index
        if force:
            self._storage.clear_repo(repo_path)

        try:
            with OmniSharpServer(
                solution_path,
                omnisharp_path=self._omnisharp_path,
                timeout=self._timeout,
            ) as server:
                # Get all C# files in the solution
                files = server.get_project_files()

                if not files:
                    logger.warning("No C# files found in solution")
                    return result

                total_files = len(files)
                logger.info("Indexing %d files from solution", total_files)

                if progress_callback:
                    progress_callback(0, total_files, "Starting indexing...")

                # Phase 1: Index all symbols from all files
                for idx, file_path in enumerate(files):
                    if progress_callback:
                        progress_callback(
                            idx + 1, total_files, f"Indexing symbols: {file_path}"
                        )

                    try:
                        symbols_count = self._index_file_symbols(
                            server, file_path, repo_path
                        )
                        result.symbols_indexed += symbols_count
                        result.files_indexed += 1
                    except OmniSharpError as e:
                        logger.warning("Failed to index %s: %s", file_path, e)
                        result.errors.append(f"{file_path}: {e}")
                        result.files_failed += 1

                # Phase 2: Index usages for all indexed symbols
                if progress_callback:
                    progress_callback(
                        total_files,
                        total_files,
                        "Finding usages for all symbols...",
                    )

                usages_count = self._index_all_usages(server, repo_path)
                result.usages_indexed = usages_count

        except OmniSharpError as e:
            logger.error("OmniSharp error: %s", e)
            result.errors.append(str(e))

        return result

    def _index_file_symbols(
        self,
        server: OmniSharpServer,
        file_path: str,
        repo_path: str,
    ) -> int:
        """Index all symbols from a single file.

        Args:
            server: OmniSharp server instance.
            file_path: Path to the C# file.
            repo_path: Repository root path.

        Returns:
            Number of symbols indexed.
        """
        structure = server.get_code_structure(file_path)

        if not structure.elements:
            return 0

        count = 0
        for element in structure.elements:
            count += self._index_code_element(element, file_path, repo_path, None)

        return count

    def _index_code_element(
        self,
        element: CodeElement,
        file_path: str,
        repo_path: str,
        parent_qualified_name: str | None,
    ) -> int:
        """Recursively index a code element and its children.

        Args:
            element: CodeElement from OmniSharp.
            file_path: Path to the source file.
            repo_path: Repository root path.
            parent_qualified_name: Qualified name of parent element.

        Returns:
            Number of symbols indexed (including children).
        """
        count = 0

        # Build qualified name
        qualified_name = element.name
        if parent_qualified_name:
            qualified_name = f"{parent_qualified_name}.{element.name}"

        # Get location from ranges
        location = self._extract_location(element, file_path)

        # Map symbol kind
        kind = self.SYMBOL_KIND_MAP.get(element.kind.lower(), NodeKind.VARIABLE)

        # Generate node ID
        node_id = f"{file_path}:{element.name}:{location.start_line}"

        # Extract properties
        metadata = {}
        if element.properties:
            if "accessibility" in element.properties:
                metadata["accessibility"] = element.properties["accessibility"]
            if "static" in element.properties:
                metadata["static"] = element.properties["static"]

        # Create graph node
        graph_node = GraphNode(
            id=node_id,
            name=element.name,
            kind=kind,
            location=location,
            qualified_name=qualified_name,
            signature=element.display_name,
            metadata=metadata,
        )

        self._storage.create_node(graph_node, repo_path)
        count += 1

        # Index children recursively
        if element.children:
            for child in element.children:
                count += self._index_code_element(
                    child, file_path, repo_path, qualified_name
                )

                # Create containment edge
                child_location = self._extract_location(child, file_path)
                child_id = f"{file_path}:{child.name}:{child_location.start_line}"

                edge = GraphEdge(
                    source_id=node_id,
                    target_id=child_id,
                    kind=EdgeKind.CONTAINS,
                )
                try:
                    self._storage.create_edge(edge)
                except Exception:
                    # Skip if child node doesn't exist (shouldn't happen)
                    pass

        return count

    def _extract_location(self, element: CodeElement, file_path: str) -> Location:
        """Extract location from CodeElement ranges.

        Args:
            element: CodeElement with ranges.
            file_path: Path to the source file.

        Returns:
            Location object.
        """
        # OmniSharp uses 0-indexed lines, code-intel uses 1-indexed
        start_line = 1
        start_column = 0
        end_line = 1
        end_column = 0

        if element.ranges:
            # Prefer "name" range for precise location, fall back to "full"
            range_data = element.ranges.get("name") or element.ranges.get("full")
            if range_data:
                start_line = range_data.start.line + 1  # Convert to 1-indexed
                start_column = range_data.start.column
                end_line = range_data.end.line + 1
                end_column = range_data.end.column

        return Location(
            file_path=file_path,
            start_line=start_line,
            start_column=start_column,
            end_line=end_line,
            end_column=end_column,
        )

    def _index_all_usages(
        self,
        server: OmniSharpServer,
        repo_path: str,
    ) -> int:
        """Index usages for all symbols in the repository.

        For each callable symbol (method, property, event), queries OmniSharp
        to find all usages and creates CALLS edges.

        Args:
            server: OmniSharp server instance.
            repo_path: Repository root path.

        Returns:
            Number of edges created.
        """
        # Get all nodes that could be called (methods, properties, events)
        callable_kinds = [
            NodeKind.METHOD,
            NodeKind.PROPERTY,
            NodeKind.FUNCTION,
        ]

        edges_created = 0
        all_nodes = self._storage.get_all_nodes(repo_path)

        for node in all_nodes:
            if node.kind not in callable_kinds:
                continue

            # Query OmniSharp for usages
            try:
                response = server.find_usages(
                    node.location.file_path,
                    node.location.start_line - 1,  # Convert to 0-indexed
                    node.location.start_column,
                    exclude_definition=True,
                )

                if not response.quick_fixes:
                    continue

                for usage in response.quick_fixes:
                    # Find the node that contains this usage
                    caller_node = self._find_containing_node(
                        usage.file_name,
                        usage.line + 1,  # Convert to 1-indexed
                        repo_path,
                    )

                    if caller_node and caller_node.id != node.id:
                        edge = GraphEdge(
                            source_id=caller_node.id,
                            target_id=node.id,
                            kind=EdgeKind.CALLS,
                            location=Location(
                                file_path=usage.file_name,
                                start_line=usage.line + 1,
                                start_column=usage.column,
                                end_line=usage.end_line + 1,
                                end_column=usage.end_column,
                            ),
                        )
                        try:
                            self._storage.create_edge(edge)
                            edges_created += 1
                        except Exception:
                            # Edge may already exist or node not found
                            pass

            except OmniSharpError as e:
                logger.debug(
                    "Failed to find usages for %s: %s", node.qualified_name, e
                )

        return edges_created

    def _find_containing_node(
        self,
        file_path: str,
        line: int,
        repo_path: str,
    ) -> GraphNode | None:
        """Find the node that contains a given location.

        Args:
            file_path: Path to the source file.
            line: Line number (1-indexed).
            repo_path: Repository root path.

        Returns:
            GraphNode that contains the location, or None.
        """
        # Get all nodes in the file
        nodes = self._storage.get_nodes_by_file(file_path, repo_path)

        # Find the smallest node that contains the line
        best_node = None
        best_span = float("inf")

        for node in nodes:
            loc = node.location
            if loc.start_line <= line <= loc.end_line:
                span = loc.end_line - loc.start_line
                # Prefer methods over classes (smaller span)
                if span < best_span:
                    best_span = span
                    best_node = node
                elif span == best_span and node.kind == NodeKind.METHOD:
                    # Prefer method if same span
                    best_node = node

        return best_node

    def clear_repository(self, repo_path: Path | str) -> int:
        """Clear all indexed data for a repository.

        Args:
            repo_path: Path to the repository root.

        Returns:
            Number of nodes deleted.
        """
        repo_path_str = str(Path(repo_path).resolve())
        return self._storage.clear_repo(repo_path_str)
