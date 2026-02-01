"""Main client interface for code-intel."""

from __future__ import annotations

import logging
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
from code_intel.profile.schema import (
    FunctionStats,
    Profile,
    ProfileComparison,
    ProfileMetadata,
)
from code_intel.profile.speedscope import SpeedscopeParser
from code_intel.profile.storage import ProfileStorage

if TYPE_CHECKING:
    from code_intel.parser.base import BaseParser

logger = logging.getLogger(__name__)


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
class ProfileIngestResult:
    """Result of a profile ingestion operation."""

    profiles_ingested: int = 0
    """Number of profiles successfully ingested."""

    total_frames: int = 0
    """Total number of unique frames across all profiles."""

    total_functions: int = 0
    """Total number of functions with stats."""

    symbols_correlated: int = 0
    """Number of frames successfully correlated with code symbols."""

    errors: list[str] = field(default_factory=list)
    """List of error messages."""


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
        self._profile_storage = ProfileStorage(db_path)
        self._speedscope_parser = SpeedscopeParser()
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

    def index_with_roslyn(
        self,
        repo_path: Path | str,
        solution_file: Path | str | None = None,
        *,
        force: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> IndexResult:
        """Index a C# repository using Roslyn/OmniSharp for semantic analysis.

        This method provides semantic code analysis for C# codebases using
        OmniSharp's Roslyn-based engine. Unlike tree-sitter parsing, this
        captures full semantic relationships including:
        - Delegate invocations
        - Event handlers
        - Interface dispatch
        - Virtual method calls

        Args:
            repo_path: Path to the repository root directory.
            solution_file: Optional path to .sln or .csproj file. If None,
                          auto-discovers solution files in the repository.
            force: If True, re-index even if already indexed (clears existing data).
            progress_callback: Optional callback for progress updates.
                              Called with (current, total, message).

        Returns:
            IndexResult with indexing statistics.

        Raises:
            ImportError: If omnisharp dependencies are not available.

        Example:
            client = CodeIntelClient()

            # Index with auto-discovery
            result = client.index_with_roslyn("/path/to/csharp-repo")

            # Index specific solution
            result = client.index_with_roslyn(
                "/path/to/repo",
                solution_file="/path/to/repo/MySolution.sln"
            )
        """
        # Import here to avoid hard dependency on OmniSharp
        from code_intel.indexer.roslyn import RoslynIndexer

        repo_path = Path(repo_path).resolve()

        # Create RoslynIndexer sharing our storage's database
        # This ensures data consistency between tree-sitter and Roslyn indexing
        indexer = RoslynIndexer(db_path=self._db_path)

        # Adapt progress callback if provided
        roslyn_callback = None
        if progress_callback:
            def roslyn_callback(current: int, total: int, message: str) -> None:
                # Roslyn callback uses 'message' while client uses 'file_path'
                # We pass the message as-is since it may contain file paths
                progress_callback(current, total, message)

        # Perform indexing
        roslyn_result = indexer.index_repo(
            repo_path,
            solution_file=solution_file,
            force=force,
            progress_callback=roslyn_callback,
        )

        # Convert RoslynIndexResult to IndexResult for API consistency
        return IndexResult(
            files_indexed=roslyn_result.files_indexed,
            files_failed=roslyn_result.files_failed,
            nodes_created=roslyn_result.symbols_indexed,
            edges_created=roslyn_result.usages_indexed,
            errors=roslyn_result.errors,
        )

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
    # Profile Analysis Methods
    # =========================================================================

    def ingest_profile(
        self,
        profile_path: Path | str,
        repo_path: Path | str | None = None,
        *,
        metadata: ProfileMetadata | None = None,
        correlate_symbols: bool = True,
    ) -> ProfileIngestResult:
        """Ingest a speedscope profile and store it for analysis.

        Parses the profile, computes per-function statistics, and optionally
        correlates profile frames with code-intel symbol graph nodes.

        Args:
            profile_path: Path to the speedscope JSON file.
            repo_path: Repository path for scoping symbol correlation.
            metadata: Optional metadata (commit SHA, scenario, tags).
            correlate_symbols: If True, attempt to match frames to code symbols.

        Returns:
            ProfileIngestResult with ingestion statistics.

        Example:
            result = client.ingest_profile(
                "profile.speedscope.json",
                repo_path="/path/to/repo",
                metadata=ProfileMetadata(
                    commit_sha="abc123",
                    scenario="startup",
                    tags=["regression-test"],
                ),
            )
            print(f"Ingested {result.profiles_ingested} profiles")
        """
        result = ProfileIngestResult()
        repo_path_str = self._resolve_repo_path(repo_path) if repo_path else None

        try:
            profiles = self._speedscope_parser.parse_file(
                profile_path,
                repo_path=repo_path_str,
                metadata=metadata,
            )
        except Exception as e:
            result.errors.append(f"Failed to parse profile: {e}")
            return result

        for profile in profiles:
            try:
                self._profile_storage.create_profile(profile)
                result.profiles_ingested += 1
                result.total_frames += len(profile.frames)
                result.total_functions += len(profile.function_stats)

                # Correlate with code graph if requested
                if correlate_symbols and repo_path_str:
                    correlated = self._correlate_profile_symbols(
                        profile, repo_path_str
                    )
                    result.symbols_correlated += correlated
            except Exception as e:
                result.errors.append(f"Failed to store profile '{profile.name}': {e}")

        return result

    def get_profile(self, profile_id: str) -> Profile | None:
        """Retrieve a profile by ID.

        Args:
            profile_id: Unique identifier of the profile.

        Returns:
            Profile if found, None otherwise.
        """
        return self._profile_storage.get_profile(profile_id)

    def list_profiles(
        self,
        repo_path: Path | str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Profile]:
        """List profiles, optionally filtered by repository.

        Args:
            repo_path: Optional repository path filter.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of Profile objects (metadata only, no full stats).
        """
        repo_path_str = self._resolve_repo_path(repo_path) if repo_path else None
        return self._profile_storage.list_profiles(
            repo_path_str, limit=limit, offset=offset
        )

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a profile and all associated data.

        Args:
            profile_id: ID of the profile to delete.

        Returns:
            True if deleted, False if not found.
        """
        return self._profile_storage.delete_profile(profile_id)

    def top_functions(
        self,
        profile_id: str,
        *,
        limit: int = 10,
        by: str = "self",
    ) -> list[FunctionStats]:
        """Get the hottest functions in a profile.

        Args:
            profile_id: ID of the profile to query.
            limit: Maximum number of results.
            by: Sort key - 'self' for self time, 'total' for total time.

        Returns:
            List of FunctionStats sorted by the specified metric.

        Example:
            hotspots = client.top_functions(profile_id, limit=10)
            for fn in hotspots:
                print(f"{fn.name}: {fn.self_percentage:.1f}% self time")
        """
        return self._profile_storage.get_top_functions(
            profile_id, limit=limit, by=by
        )

    def compare_profiles(
        self,
        before_id: str,
        after_id: str,
        *,
        threshold_pct: float = 5.0,
    ) -> ProfileComparison | None:
        """Compare two profiles to find regressions and improvements.

        Args:
            before_id: ID of the 'before' profile (baseline).
            after_id: ID of the 'after' profile (comparison).
            threshold_pct: Minimum percentage change to report (default 5%).

        Returns:
            ProfileComparison with deltas, or None if profiles not found.

        Example:
            comparison = client.compare_profiles(baseline_id, new_id)
            if comparison:
                for reg in comparison.regressions[:5]:
                    print(f"REGRESSION: {reg.name} +{reg.self_weight_change_pct:.1f}%")
        """
        return self._profile_storage.compare_profiles(
            before_id, after_id, threshold_pct=threshold_pct
        )

    def function_trend(
        self,
        function_name: str,
        repo_path: Path | str | None = None,
        *,
        limit: int = 10,
    ) -> list[tuple[Profile, FunctionStats]]:
        """Get a function's performance over time across profiles.

        Useful for tracking whether a function is getting slower or faster
        across multiple profiling sessions.

        Args:
            function_name: Name of the function to track.
            repo_path: Optional repository path filter.
            limit: Maximum number of profiles to include.

        Returns:
            List of (Profile, FunctionStats) tuples, ordered by profile date.

        Example:
            trend = client.function_trend("process_data", limit=5)
            for profile, stats in trend:
                print(f"{profile.name}: {stats.self_weight:.2f}ms")
        """
        repo_path_str = self._resolve_repo_path(repo_path) if repo_path else None
        return self._profile_storage.get_function_trend(
            function_name, repo_path_str, limit=limit
        )

    def hot_callers(
        self,
        symbol: str,
        repo_path: Path | str,
        *,
        profile_id: str | None = None,
    ) -> list[tuple[GraphNode, FunctionStats | None]]:
        """Find callers of a function with their performance data.

        Combines code-intel call graph analysis with profile data to show
        which callers of a function are contributing to its runtime cost.

        Args:
            symbol: Name of the function to find callers for.
            repo_path: Repository path for the code graph.
            profile_id: Optional profile ID to get performance data from.

        Returns:
            List of (GraphNode, FunctionStats) tuples. FunctionStats is None
            if no profile data is available for that caller.

        Example:
            callers = client.hot_callers("slow_function", repo_path, profile_id=pid)
            for caller, stats in callers:
                if stats:
                    print(f"{caller.name}: {stats.self_weight:.2f}ms")
                else:
                    print(f"{caller.name}: no profile data")
        """
        repo_path_str = self._resolve_repo_path(repo_path)

        # Get callers from code graph
        callers = self._storage.find_callers(symbol, repo_path_str)

        # If no profile specified, return callers without stats
        if not profile_id:
            return [(caller, None) for caller in callers]

        # Get profile and build stats lookup
        profile = self._profile_storage.get_profile(profile_id)
        if not profile:
            return [(caller, None) for caller in callers]

        stats_by_name: dict[str, FunctionStats] = {
            s.name: s for s in profile.function_stats
        }

        # Match callers to stats
        result: list[tuple[GraphNode, FunctionStats | None]] = []
        for caller in callers:
            # Try exact name match first
            stats = stats_by_name.get(caller.name)

            # Try qualified name if no exact match
            if not stats and caller.qualified_name:
                stats = stats_by_name.get(caller.qualified_name)

            result.append((caller, stats))

        # Sort by stats weight if available
        result.sort(
            key=lambda x: x[1].self_weight if x[1] else 0,
            reverse=True,
        )

        return result

    # =========================================================================
    # Private methods
    # =========================================================================

    def _correlate_profile_symbols(
        self,
        profile: Profile,
        repo_path: str,
    ) -> int:
        """Correlate profile frames with code graph symbols.

        Attempts to match each frame in the profile to a node in the code
        graph based on function name and file path.

        Args:
            profile: Profile to correlate.
            repo_path: Repository path for the code graph.

        Returns:
            Number of frames successfully correlated.
        """
        correlations: dict[int, str] = {}

        for idx, frame in enumerate(profile.frames):
            # Try to find a matching symbol
            symbol_id = self._find_symbol_for_frame(frame, repo_path)
            if symbol_id:
                correlations[idx] = symbol_id

        if correlations:
            self._profile_storage.update_symbol_correlations(
                profile.id, correlations
            )

        return len(correlations)

    def _find_symbol_for_frame(self, frame, repo_path: str) -> str | None:
        """Find a code graph symbol matching a profile frame.

        Uses multiple strategies:
        1. If file+line available, find symbol at that location
        2. Match by function name
        3. Match by qualified name patterns

        Args:
            frame: Profile frame to match.
            repo_path: Repository path for scoping.

        Returns:
            Node ID if found, None otherwise.
        """
        # Parse the frame name to get a searchable symbol
        name = frame.to_qualified_name()

        # Extract the simple function name (last component)
        simple_name = name.split(".")[-1] if "." in name else name

        # Strategy 1: If we have file info, find by location
        if frame.file and frame.line:
            nodes = self._storage.get_nodes_by_file(frame.file, repo_path)
            for node in nodes:
                if node.location.start_line == frame.line:
                    return node.id
                # Also check if the line is within the node's range
                if (
                    node.location.start_line <= frame.line
                    and node.location.end_line >= frame.line
                    and node.name == simple_name
                ):
                    return node.id

        # Strategy 2: Match by simple name
        nodes = self._storage.get_nodes_by_name(simple_name, repo_path)
        if len(nodes) == 1:
            return nodes[0].id

        # Strategy 3: If multiple matches, try qualified name
        if len(nodes) > 1:
            for node in nodes:
                if node.qualified_name and node.qualified_name == name:
                    return node.id
                # Check if qualified name ends with our search name
                if node.qualified_name and node.qualified_name.endswith(f".{name}"):
                    return node.id

        # Strategy 4: Return first match if any
        if nodes:
            return nodes[0].id

        return None

    # =========================================================================
    # Private methods (continued)
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

            # Resolve target node ID using target_module hint if available
            target_id = node_id_map.get(parsed_edge.target_name)
            if not target_id:
                target_module = parsed_edge.metadata.get("target_module")
                target_id = self._find_node_id_by_name(
                    parsed_edge.target_name, file_path_str, repo_path,
                    target_module=target_module
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
        *,
        target_module: str | None = None,
    ) -> str | None:
        """Find a node ID by name, with optional module hint for cross-file resolution.

        Search priority:
        1. If target_module is provided, search that specific module/file first
        2. Search in current file
        3. Fall back to repo-wide search (returns first match if unique)

        Special handling for <module> which represents the current file/module.

        Args:
            name: The symbol name to find.
            file_path: Current file path for same-file resolution.
            repo_path: Repository root path for scoping.
            target_module: Optional module path hint (e.g., 'foundry.jira') for
                          cross-file symbol resolution. Converted to file path.

        Returns:
            Node ID if found, None otherwise.
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

        # If we have a target_module hint, try to resolve via that file first
        if target_module:
            target_file_path = self._module_to_file_path(target_module, repo_path)
            if target_file_path:
                nodes = self._storage.get_nodes_by_file(target_file_path, repo_path)
                for node in nodes:
                    if node.name == name or node.qualified_name == name:
                        return node.id
                    # Also check for qualified names like ClassName.method
                    if node.qualified_name and node.qualified_name.endswith(f".{name}"):
                        return node.id

        # Search in current file first
        nodes = self._storage.get_nodes_by_file(file_path, repo_path)
        for node in nodes:
            if node.name == name or node.qualified_name == name:
                return node.id

        # Search in entire repo
        nodes = self._storage.get_nodes_by_name(name, repo_path)
        if nodes:
            # If there's only one match, return it
            # If there are multiple and no module hint, we can't disambiguate
            if len(nodes) == 1:
                return nodes[0].id
            # Multiple matches without hint - best effort: return first
            # A future enhancement could rank by proximity or frequency
            return nodes[0].id

        return None

    def _module_to_file_path(self, module_path: str, repo_path: str) -> str | None:
        """Convert a Python module path to a file system path.

        Tries multiple resolution strategies:
        1. Direct module path to .py file (foundry.jira -> foundry/jira.py)
        2. Package __init__.py (foundry.jira -> foundry/jira/__init__.py)
        3. src/ prefix variation (src/foundry/jira.py)

        Args:
            module_path: Dotted module path (e.g., 'foundry.jira').
            repo_path: Repository root path.

        Returns:
            Absolute file path if found, None otherwise.
        """
        if not module_path:
            return None

        repo = Path(repo_path)
        parts = module_path.split(".")

        # Try direct .py file
        candidate = repo / "/".join(parts[:-1]) / f"{parts[-1]}.py" if len(parts) > 1 else repo / f"{parts[0]}.py"
        if candidate.exists():
            return str(candidate)

        # Try full path as .py
        full_path = repo / ("/".join(parts) + ".py")
        if full_path.exists():
            return str(full_path)

        # Try as package __init__.py
        package_init = repo / "/".join(parts) / "__init__.py"
        if package_init.exists():
            return str(package_init)

        # Try with src/ prefix
        src_direct = repo / "src" / "/".join(parts[:-1]) / f"{parts[-1]}.py" if len(parts) > 1 else repo / "src" / f"{parts[0]}.py"
        if src_direct.exists():
            return str(src_direct)

        src_full = repo / "src" / ("/".join(parts) + ".py")
        if src_full.exists():
            return str(src_full)

        src_init = repo / "src" / "/".join(parts) / "__init__.py"
        if src_init.exists():
            return str(src_init)

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
            # XAML node types
            "page": NodeKind.CLASS,  # XAML page (x:Class)
            "named_element": NodeKind.VARIABLE,  # XAML named element (x:Name)
            "resource": NodeKind.CONSTANT,  # XAML resource (x:Key)
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
            # XAML edge types (all map to CALLS or REFERENCES)
            "event_handler": EdgeKind.CALLS,  # XAML event -> handler method
            "binding": EdgeKind.REFERENCES,  # XAML binding expression
            "command": EdgeKind.CALLS,  # XAML command binding
            "resource_ref": EdgeKind.REFERENCES,  # StaticResource/DynamicResource
            "template_binding": EdgeKind.REFERENCES,  # TemplateBinding
        }
        return mapping.get(kind_str.lower(), EdgeKind.REFERENCES)

    def _infer_language(self, path: Path) -> str:
        """Infer language from file extension.

        First checks a built-in map for common languages, then falls back
        to checking registered parsers' file extensions.

        Args:
            path: File path.

        Returns:
            Language name.

        Raises:
            ValueError: If language cannot be inferred.
        """
        # Built-in extension map for common languages
        extension_map = {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".cs": "csharp",
        }

        ext = path.suffix.lower()
        language = extension_map.get(ext)

        # Fallback: check registered parsers' file extensions
        if language is None:
            for parser_lang, parser in self._parsers.items():
                if ext in parser.file_extensions:
                    language = parser_lang
                    break

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
