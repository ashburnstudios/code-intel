"""Main client interface for code-intel."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from code_intel.graph.schema import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)
from code_intel.graph.storage import GraphStorage

if TYPE_CHECKING:
    from code_intel.parser.base import BaseParser, ParseResult


@dataclass
class IndexResult:
    """Result of an indexing operation.

    Contains statistics about what was indexed and any errors encountered.
    """

    files_indexed: int = 0
    """Number of files successfully indexed."""

    files_skipped: int = 0
    """Number of files skipped (no parser, excluded, etc.)."""

    files_failed: int = 0
    """Number of files that failed to parse."""

    nodes_created: int = 0
    """Total number of nodes (symbols) created."""

    edges_created: int = 0
    """Total number of edges (relationships) created."""

    errors: list[str] = field(default_factory=list)
    """List of error messages from failed files."""


@dataclass
class RepoStats:
    """Statistics about an indexed repository."""

    repo_path: str
    """Path to the repository root."""

    total_files: int = 0
    """Total number of indexed files."""

    total_nodes: int = 0
    """Total number of nodes (symbols) in the graph."""

    total_edges: int = 0
    """Total number of edges (relationships) in the graph."""

    nodes_by_kind: dict[str, int] = field(default_factory=dict)
    """Count of nodes grouped by NodeKind."""

    edges_by_kind: dict[str, int] = field(default_factory=dict)
    """Count of edges grouped by EdgeKind."""


# Type alias for progress callback
ProgressCallback = Callable[[int, int, str], None]
"""Callback for progress updates: (current, total, file_path)."""


class CodeIntelClient:
    """Synchronous client for code intelligence operations.

    Provides methods for indexing codebases, finding callers/references,
    and performing impact analysis.

    Example:
        client = CodeIntelClient()
        client.register_parser(PythonParser())

        # Index a repository
        result = client.index_repo("/path/to/repo")
        print(f"Indexed {result.files_indexed} files")

        # Query the graph
        callers = client.find_callers("my_function", "/path/to/repo")
        for caller in callers:
            print(f"{caller.name} at {caller.location.file_path}:{caller.location.start_line}")
    """

    # Default exclude patterns for common non-source directories
    DEFAULT_EXCLUDE_PATTERNS: list[str] = [
        "**/node_modules/**",
        "**/.git/**",
        "**/__pycache__/**",
        "**/.venv/**",
        "**/venv/**",
        "**/.tox/**",
        "**/dist/**",
        "**/build/**",
        "**/.eggs/**",
        "**/*.egg-info/**",
        "**/.mypy_cache/**",
        "**/.pytest_cache/**",
    ]

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise the client.

        Args:
            db_path: Path to the SQLite database file. If None, uses
                     an in-memory database (useful for testing).
        """
        self._db_path = Path(db_path) if db_path else None
        self._storage = GraphStorage(db_path)
        self._parsers: dict[str, BaseParser] = {}

    def register_parser(self, parser: BaseParser) -> None:
        """Register a parser for a specific language.

        Args:
            parser: Parser instance to register.
        """
        self._parsers[parser.language_name] = parser

    def index_repo(
        self,
        repo_path: Path | str,
        *,
        force: bool = False,
        extensions: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> IndexResult:
        """Index a repository.

        Discovers all supported source files in the repository and indexes
        them into the graph database.

        Args:
            repo_path: Path to repository root.
            force: If True, re-index even if already indexed (clears existing data).
            extensions: File extensions to include (e.g., ['.py', '.ts']).
                       If None, uses extensions from registered parsers.
            exclude_patterns: Glob patterns to exclude. Defaults to common
                             non-source directories (node_modules, .git, etc.).
            progress_callback: Optional callback for progress updates.
                              Called with (current_file_index, total_files, file_path).

        Returns:
            IndexResult with statistics about the indexing operation.
        """
        repo_path = Path(repo_path).resolve()
        repo_path_str = str(repo_path)

        result = IndexResult()

        # Clear existing data if force re-index
        if force:
            self._storage.clear_repo(repo_path_str)

        # Determine which extensions to look for
        if extensions is None:
            extensions = self._get_supported_extensions()

        if not extensions:
            return result  # No parsers registered, nothing to do

        # Set up exclude patterns
        if exclude_patterns is None:
            exclude_patterns = self.DEFAULT_EXCLUDE_PATTERNS.copy()

        # Discover all files to index
        files_to_index = self._discover_files(repo_path, extensions, exclude_patterns)
        total_files = len(files_to_index)

        # Index each file
        for idx, file_path in enumerate(files_to_index):
            if progress_callback:
                progress_callback(idx + 1, total_files, str(file_path))

            try:
                file_result = self._index_single_file(file_path, repo_path_str)
                result.files_indexed += 1
                result.nodes_created += file_result.nodes_created
                result.edges_created += file_result.edges_created
                result.errors.extend(file_result.errors)
            except Exception as e:
                result.files_failed += 1
                result.errors.append(f"{file_path}: {e}")

        return result

    def index_file(
        self,
        file_path: Path | str,
        repo_path: Path | str,
        *,
        language: str | None = None,
    ) -> IndexResult:
        """Index a single file (for incremental updates).

        Clears any existing data for this file and re-indexes it.

        Args:
            file_path: Path to the source file.
            repo_path: Path to the repository root (for scoping).
            language: Language name. If None, inferred from extension.

        Returns:
            IndexResult with statistics about the indexing operation.

        Raises:
            ValueError: If no parser is registered for the language.
            FileNotFoundError: If the file does not exist.
        """
        file_path = Path(file_path).resolve()
        repo_path_str = str(Path(repo_path).resolve())

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if language is None:
            language = self._infer_language(file_path)

        if language not in self._parsers:
            raise ValueError(f"No parser registered for language: {language}")

        # Clear existing data for this file
        self._storage.clear_file(str(file_path), repo_path_str)

        # Index the file
        return self._index_single_file(file_path, repo_path_str, language)

    def find_callers(
        self,
        symbol: str,
        repo_path: Path | str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[GraphNode]:
        """Find all callers of a function/method.

        Args:
            symbol: Name of the function/method to find callers for.
            repo_path: Repository path to scope the search. Required for
                      multi-repo databases.
            limit: Maximum number of results to return.
            offset: Number of results to skip (for pagination).

        Returns:
            List of GraphNode objects representing callers.
        """
        repo_path_str = self._resolve_repo_path(repo_path)
        return self._storage.find_callers(
            symbol, repo_path_str, limit=limit, offset=offset
        )

    def find_callees(
        self,
        symbol: str,
        repo_path: Path | str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[GraphNode]:
        """Find all functions/methods called by a function.

        Args:
            symbol: Name of the function/method to find callees for.
            repo_path: Repository path to scope the search.
            limit: Maximum number of results to return.
            offset: Number of results to skip (for pagination).

        Returns:
            List of GraphNode objects representing callees.
        """
        repo_path_str = self._resolve_repo_path(repo_path)
        return self._storage.find_callees(
            symbol, repo_path_str, limit=limit, offset=offset
        )

    def find_references(
        self,
        symbol: str,
        repo_path: Path | str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[GraphNode]:
        """Find all references to a symbol.

        This is broader than find_callers as it includes all types of
        references (calls, imports, type references, inheritance, etc.).

        Args:
            symbol: Name of the symbol to find references for.
            repo_path: Repository path to scope the search.
            limit: Maximum number of results to return.
            offset: Number of results to skip (for pagination).

        Returns:
            List of GraphNode objects representing referencing nodes.
        """
        repo_path_str = self._resolve_repo_path(repo_path)
        return self._storage.find_references(
            symbol, repo_path_str, limit=limit, offset=offset
        )

    def get_symbol_info(
        self,
        symbol: str,
        repo_path: Path | str | None = None,
        *,
        qualified_name: str | None = None,
        node_type: NodeKind | None = None,
    ) -> GraphNode | None:
        """Get information about a symbol.

        Args:
            symbol: Name of the symbol to look up.
            repo_path: Repository path to scope the search.
            qualified_name: Optional fully qualified name for disambiguation.
            node_type: Optional node type filter for disambiguation.

        Returns:
            GraphNode with symbol information, or None if not found.
        """
        repo_path_str = self._resolve_repo_path(repo_path)
        return self._storage.get_symbol_info(
            symbol,
            repo_path_str,
            qualified_name=qualified_name,
            node_type=node_type,
        )

    def get_stats(self, repo_path: Path | str) -> RepoStats:
        """Get indexing statistics for a repository.

        Args:
            repo_path: Path to the repository root.

        Returns:
            RepoStats with counts and breakdowns.
        """
        repo_path_str = str(Path(repo_path).resolve())

        # Get all nodes and edges for this repo
        nodes = self._storage.get_all_nodes(repo_path_str)
        edges = self._storage.get_all_edges(repo_path_str)

        # Count unique files
        unique_files = {node.location.file_path for node in nodes}

        # Count by kind
        nodes_by_kind: dict[str, int] = {}
        for node in nodes:
            kind = node.kind.value
            nodes_by_kind[kind] = nodes_by_kind.get(kind, 0) + 1

        edges_by_kind: dict[str, int] = {}
        for edge in edges:
            kind = edge.kind.value
            edges_by_kind[kind] = edges_by_kind.get(kind, 0) + 1

        return RepoStats(
            repo_path=repo_path_str,
            total_files=len(unique_files),
            total_nodes=len(nodes),
            total_edges=len(edges),
            nodes_by_kind=nodes_by_kind,
            edges_by_kind=edges_by_kind,
        )

    # =========================================================================
    # Private methods
    # =========================================================================

    def _get_supported_extensions(self) -> list[str]:
        """Get all file extensions supported by registered parsers."""
        extensions = []
        for parser in self._parsers.values():
            extensions.extend(parser.file_extensions)
        return extensions

    def _discover_files(
        self,
        repo_path: Path,
        extensions: list[str],
        exclude_patterns: list[str],
    ) -> list[Path]:
        """Discover all source files to index.

        Args:
            repo_path: Repository root path.
            extensions: File extensions to include.
            exclude_patterns: Glob patterns to exclude.

        Returns:
            List of file paths to index.
        """
        files: list[Path] = []

        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue

            # Check extension
            if file_path.suffix.lower() not in extensions:
                continue

            # Check exclude patterns
            if self._matches_exclude_pattern(file_path, repo_path, exclude_patterns):
                continue

            files.append(file_path)

        return sorted(files)  # Sort for deterministic ordering

    def _matches_exclude_pattern(
        self,
        file_path: Path,
        repo_path: Path,
        exclude_patterns: list[str],
    ) -> bool:
        """Check if a file matches any exclude pattern.

        Handles various glob patterns:
        - **/.venv/** - directory anywhere in path
        - **/*.pyc - file extension anywhere in path
        - .venv/** - directory at root
        - node_modules/*/*.py - specific path pattern
        """
        # Get relative path for pattern matching
        try:
            rel_path = file_path.relative_to(repo_path)
        except ValueError:
            rel_path = file_path

        rel_str = str(rel_path)
        parts = rel_path.parts

        for pattern in exclude_patterns:
            # Pattern like **/.venv/** - directory anywhere in path
            if pattern.startswith("**/") and pattern.endswith("/**"):
                dir_name = pattern[3:-3]  # Extract e.g., ".venv" from "**/.venv/**"
                if dir_name in parts:
                    return True
            # Pattern like **/*.pyc - file extension match anywhere
            elif pattern.startswith("**/") and "*" not in pattern[3:]:
                # Simple suffix like **/*.pyc
                suffix = pattern[3:]  # e.g., "*.pyc"
                if suffix.startswith("*."):
                    ext = suffix[1:]  # e.g., ".pyc"
                    if rel_str.endswith(ext):
                        return True
                elif rel_str.endswith(suffix) or f"/{suffix}" in f"/{rel_str}":
                    return True
            # Pattern like .venv/** - directory at root
            elif pattern.endswith("/**"):
                prefix = pattern[:-3]
                if rel_str.startswith(prefix) or rel_str.startswith(prefix + "/"):
                    return True
            else:
                # Fallback to Path.match for other patterns like node_modules/*/*.py
                if rel_path.match(pattern):
                    return True
                if file_path.match(pattern):
                    return True

        return False

    def _index_single_file(
        self,
        file_path: Path,
        repo_path: str,
        language: str | None = None,
    ) -> IndexResult:
        """Index a single file into the graph.

        Args:
            file_path: Path to the source file.
            repo_path: Repository root path.
            language: Language name. If None, inferred from extension.

        Returns:
            IndexResult with statistics.
        """
        result = IndexResult()

        if language is None:
            language = self._infer_language(file_path)

        if language not in self._parsers:
            result.files_skipped += 1
            return result

        parser = self._parsers[language]

        # Parse the file
        parse_result = parser.parse_to_result(file_path)

        # Track parse errors
        result.errors.extend(parse_result.errors)

        # Convert parsed nodes to GraphNodes and store
        file_path_str = str(file_path)
        node_id_map: dict[str, str] = {}  # Maps qualified_name -> node_id

        for parsed_node in parse_result.nodes:
            # Generate unique node ID
            node_id = f"{file_path_str}:{parsed_node.name}:{parsed_node.start_line}"

            # Map NodeKind from string
            kind = self._map_node_kind(parsed_node.node_type)

            location = Location(
                file_path=file_path_str,
                start_line=parsed_node.start_line,
                start_column=parsed_node.start_column,
                end_line=parsed_node.end_line,
                end_column=parsed_node.end_column,
            )

            graph_node = GraphNode(
                id=node_id,
                name=parsed_node.name,
                kind=kind,
                location=location,
                qualified_name=parsed_node.qualified_name,
                signature=parsed_node.signature,
                docstring=parsed_node.docstring,
                metadata=parsed_node.metadata,
            )

            self._storage.create_node(graph_node, repo_path)
            result.nodes_created += 1

            # Track for edge resolution
            if parsed_node.qualified_name:
                node_id_map[parsed_node.qualified_name] = node_id

        # Convert parsed edges to GraphEdges and store
        for parsed_edge in parse_result.edges:
            # Resolve source node ID
            source_id = node_id_map.get(parsed_edge.source_name)
            if not source_id:
                # Try to find by name in the current file
                source_id = self._find_node_id_by_name(
                    parsed_edge.source_name, file_path_str, repo_path
                )

            # Resolve target node ID
            target_id = node_id_map.get(parsed_edge.target_name)
            if not target_id:
                target_id = self._find_node_id_by_name(
                    parsed_edge.target_name, file_path_str, repo_path
                )

            # Skip edges where we can't resolve both ends
            if not source_id or not target_id:
                continue

            # Map EdgeKind from string
            edge_kind = self._map_edge_kind(parsed_edge.edge_type)

            # Create location if available
            edge_location = None
            if parsed_edge.source_location:
                line, column = parsed_edge.source_location
                if line is not None:
                    edge_location = Location(
                        file_path=file_path_str,
                        start_line=line,
                        start_column=column or 0,
                        end_line=line,
                        end_column=column or 0,
                    )

            graph_edge = GraphEdge(
                source_id=source_id,
                target_id=target_id,
                kind=edge_kind,
                location=edge_location,
                metadata=parsed_edge.metadata,
            )

            self._storage.create_edge(graph_edge)
            result.edges_created += 1

        return result

    def _find_node_id_by_name(
        self,
        name: str,
        file_path: str,
        repo_path: str,
    ) -> str | None:
        """Find a node ID by name, searching current file first then repo.

        Special handling for <module> which represents the current file/module.
        """
        # Handle special <module> placeholder
        if name == "<module>":
            # Find the module node for this file
            nodes = self._storage.get_nodes_by_file(file_path, repo_path)
            for node in nodes:
                if node.kind == NodeKind.MODULE:
                    return node.id
            # No explicit module node - return None to skip this edge
            # (Cannot use synthetic ID as it would violate FK constraint)
            return None

        # Search in current file first
        nodes = self._storage.get_nodes_by_file(file_path, repo_path)
        for node in nodes:
            if node.name == name or node.qualified_name == name:
                return node.id

        # Search in entire repo
        nodes = self._storage.get_nodes_by_name(name, repo_path)
        if nodes:
            return nodes[0].id

        return None

    def _map_node_kind(self, kind_str: str) -> NodeKind:
        """Map a string node type to NodeKind enum."""
        mapping = {
            "module": NodeKind.MODULE,
            "class": NodeKind.CLASS,
            "function": NodeKind.FUNCTION,
            "method": NodeKind.METHOD,
            "property": NodeKind.PROPERTY,
            "variable": NodeKind.VARIABLE,
            "parameter": NodeKind.PARAMETER,
            "constant": NodeKind.CONSTANT,
            "type_alias": NodeKind.TYPE_ALIAS,
            "interface": NodeKind.INTERFACE,
            "enum": NodeKind.ENUM,
            "enum_member": NodeKind.ENUM_MEMBER,
            "import": NodeKind.IMPORT,
            "decorator": NodeKind.DECORATOR,
        }
        return mapping.get(kind_str.lower(), NodeKind.VARIABLE)

    def _map_edge_kind(self, kind_str: str) -> EdgeKind:
        """Map a string edge type to EdgeKind enum."""
        mapping = {
            "contains": EdgeKind.CONTAINS,
            "inherits": EdgeKind.INHERITS,
            "implements": EdgeKind.IMPLEMENTS,
            "calls": EdgeKind.CALLS,
            "references": EdgeKind.REFERENCES,
            "imports": EdgeKind.IMPORTS,
            "instantiates": EdgeKind.INSTANTIATES,
            "returns": EdgeKind.RETURNS,
            "parameter_type": EdgeKind.PARAMETER_TYPE,
            "type_of": EdgeKind.TYPE_OF,
        }
        return mapping.get(kind_str.lower(), EdgeKind.REFERENCES)

    def _infer_language(self, path: Path) -> str:
        """Infer language from file extension.

        Args:
            path: File path.

        Returns:
            Language name.

        Raises:
            ValueError: If language cannot be inferred.
        """
        extension_map = {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".cs": "csharp",
        }

        language = extension_map.get(path.suffix.lower())
        if language is None:
            raise ValueError(f"Cannot infer language for extension: {path.suffix}")

        return language

    def _resolve_repo_path(self, repo_path: Path | str | None) -> str:
        """Resolve repo_path to a string, using a default if needed.

        For single-repo use cases, callers may not provide repo_path.
        We use an empty string as a fallback, which won't match any
        scoped queries but allows the call to proceed.
        """
        if repo_path is None:
            # For backwards compatibility, use empty string
            # This will return empty results for scoped queries
            return ""
        return str(Path(repo_path).resolve())
