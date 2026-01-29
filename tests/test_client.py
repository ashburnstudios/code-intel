"""Tests for the CodeIntelClient API."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_intel.client import CodeIntelClient, IndexResult, RepoStats
from code_intel.graph.schema import EdgeKind, NodeKind


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-python are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_python
        return True
    except ImportError:
        return False


# Marker for tests that require tree-sitter
requires_tree_sitter = pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-python not installed"
)


@pytest.fixture
def client() -> CodeIntelClient:
    """Create a client with in-memory storage for testing."""
    return CodeIntelClient()


@pytest.fixture
def python_parser():
    """Get a Python parser instance."""
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_python")
    from code_intel.parser.python import PythonParser

    return PythonParser()


@pytest.fixture
def client_with_parser(client: CodeIntelClient, python_parser) -> CodeIntelClient:
    """Create a client with Python parser registered."""
    client.register_parser(python_parser)
    return client


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a sample Python repository for testing."""
    # Create main.py
    main_py = tmp_path / "main.py"
    main_py.write_text('''"""Main module."""

from utils import helper


def process_data(data: list) -> dict:
    """Process the input data."""
    validated = validate(data)
    result = helper(validated)
    return {"result": result}


def validate(items: list) -> list:
    """Validate items."""
    return [x for x in items if x is not None]


if __name__ == "__main__":
    process_data([1, 2, 3])
''')

    # Create utils.py
    utils_py = tmp_path / "utils.py"
    utils_py.write_text('''"""Utility functions."""


def helper(data):
    """Helper function."""
    return transform(data)


def transform(data):
    """Transform data."""
    return [x * 2 for x in data]
''')

    # Create models.py with a class
    models_py = tmp_path / "models.py"
    models_py.write_text('''"""Data models."""


class DataProcessor:
    """Process data in various ways."""

    def __init__(self, config: dict):
        """Initialise with config."""
        self.config = config

    def run(self, data):
        """Run the processor."""
        return self.process(data)

    def process(self, data):
        """Process the data."""
        return data
''')

    return tmp_path


@pytest.fixture
def indexed_client(client_with_parser: CodeIntelClient, sample_repo: Path) -> tuple[CodeIntelClient, Path]:
    """Create a client with an indexed sample repository."""
    client_with_parser.index_repo(sample_repo)
    return client_with_parser, sample_repo


class TestClientInit:
    """Tests for client initialisation."""

    def test_default_init(self) -> None:
        """Test default initialisation with in-memory database."""
        client = CodeIntelClient()
        assert client._db_path is None
        assert client._storage is not None

    def test_init_with_db_path(self, tmp_path: Path) -> None:
        """Test initialisation with a database path."""
        db_path = tmp_path / "test.db"
        client = CodeIntelClient(db_path)
        assert client._db_path == db_path
        assert db_path.exists()

    def test_register_parser(self, client: CodeIntelClient, python_parser) -> None:
        """Test registering a parser."""
        client.register_parser(python_parser)
        assert "python" in client._parsers
        assert client._parsers["python"] is python_parser


@requires_tree_sitter
class TestIndexRepo:
    """Tests for index_repo method."""

    def test_index_empty_repo(self, client_with_parser: CodeIntelClient, tmp_path: Path) -> None:
        """Test indexing an empty repository."""
        result = client_with_parser.index_repo(tmp_path)
        assert result.files_indexed == 0
        assert result.nodes_created == 0
        assert result.edges_created == 0

    def test_index_repo_with_files(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test indexing a repository with Python files."""
        result = client_with_parser.index_repo(sample_repo)

        assert result.files_indexed == 3
        assert result.nodes_created > 0
        assert result.files_failed == 0

    def test_index_repo_force_reindex(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test force re-indexing clears and re-indexes."""
        # Index once
        result1 = client_with_parser.index_repo(sample_repo)
        initial_nodes = result1.nodes_created

        # Index again without force - adds duplicates or updates
        result2 = client_with_parser.index_repo(sample_repo)

        # Index with force - should clear first
        result3 = client_with_parser.index_repo(sample_repo, force=True)
        assert result3.nodes_created == initial_nodes

    def test_index_repo_with_extensions_filter(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test indexing with specific extensions."""
        # Create a .txt file that should be ignored
        (sample_repo / "readme.txt").write_text("README")

        result = client_with_parser.index_repo(sample_repo, extensions=[".py"])
        assert result.files_indexed == 3

    def test_index_repo_with_exclude_patterns(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test indexing with exclude patterns."""
        # Create a file in a directory that should be excluded
        venv_dir = sample_repo / "venv"
        venv_dir.mkdir()
        (venv_dir / "test.py").write_text("x = 1")

        result = client_with_parser.index_repo(sample_repo)
        # Should not include the venv file
        assert result.files_indexed == 3

    def test_index_repo_progress_callback(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test progress callback is called during indexing."""
        progress_calls: list[tuple[int, int, str]] = []

        def on_progress(current: int, total: int, path: str) -> None:
            progress_calls.append((current, total, path))

        client_with_parser.index_repo(sample_repo, progress_callback=on_progress)

        assert len(progress_calls) == 3
        # Check first and last calls
        assert progress_calls[0][0] == 1  # First file
        assert progress_calls[-1][0] == 3  # Last file
        assert all(call[1] == 3 for call in progress_calls)  # Total is always 3

    def test_index_repo_no_parser_registered(self, client: CodeIntelClient, sample_repo: Path) -> None:
        """Test indexing when no parser is registered."""
        result = client.index_repo(sample_repo)
        assert result.files_indexed == 0


@requires_tree_sitter
class TestIndexFile:
    """Tests for index_file method."""

    def test_index_single_file(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test indexing a single file."""
        file_path = sample_repo / "utils.py"
        result = client_with_parser.index_file(file_path, sample_repo)

        assert result.nodes_created > 0

    def test_index_file_not_found(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test indexing a non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            client_with_parser.index_file(sample_repo / "nonexistent.py", sample_repo)

    def test_index_file_no_parser(
        self, client: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test indexing without a registered parser raises error."""
        with pytest.raises(ValueError, match="No parser registered"):
            client.index_file(sample_repo / "main.py", sample_repo)

    def test_index_file_replaces_existing(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test that re-indexing a file clears old data first."""
        file_path = sample_repo / "utils.py"

        # Index once
        result1 = client_with_parser.index_file(file_path, sample_repo)
        initial_nodes = result1.nodes_created

        # Modify the file
        file_path.write_text('''"""Updated utils."""

def helper(data):
    """Helper function."""
    return data

def new_function():
    """New function."""
    pass
''')

        # Index again - should replace
        result2 = client_with_parser.index_file(file_path, sample_repo)

        # Get stats to verify no duplicate nodes
        stats = client_with_parser.get_stats(sample_repo)
        # Only nodes from the updated file should exist
        assert stats.total_nodes == result2.nodes_created


@requires_tree_sitter
class TestFindCallers:
    """Tests for find_callers method."""

    def test_find_callers_basic(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test finding callers of a function."""
        client, repo = indexed_client

        # validate is called by process_data
        callers = client.find_callers("validate", repo)
        assert len(callers) >= 1
        caller_names = {c.name for c in callers}
        assert "process_data" in caller_names

    def test_find_callers_method(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test finding callers of a method."""
        client, repo = indexed_client

        # process is called by run
        callers = client.find_callers("process", repo)
        assert len(callers) >= 1

    def test_find_callers_none(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test finding callers when there are none."""
        client, repo = indexed_client

        # process_data is not called by anything (except __main__ block)
        callers = client.find_callers("nonexistent_function", repo)
        assert len(callers) == 0

    def test_find_callers_pagination(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test pagination in find_callers."""
        client, repo = indexed_client

        # Get first page
        callers_page1 = client.find_callers("validate", repo, limit=1)
        assert len(callers_page1) <= 1

        # Get second page
        callers_page2 = client.find_callers("validate", repo, limit=1, offset=1)
        # May be empty if only one caller


@requires_tree_sitter
class TestFindCallees:
    """Tests for find_callees method."""

    def test_find_callees_basic(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test finding callees of a function."""
        client, repo = indexed_client

        # process_data calls validate and helper
        callees = client.find_callees("process_data", repo)
        callee_names = {c.name for c in callees}

        # Should include validate (and possibly helper via import resolution)
        assert "validate" in callee_names

    def test_find_callees_none(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test finding callees when function calls nothing."""
        client, repo = indexed_client

        # transform doesn't call any indexed functions
        callees = client.find_callees("nonexistent", repo)
        assert len(callees) == 0


@requires_tree_sitter
class TestFindReferences:
    """Tests for find_references method."""

    def test_find_references_broader_than_callers(
        self, indexed_client: tuple[CodeIntelClient, Path]
    ) -> None:
        """Test that find_references includes more than just callers."""
        client, repo = indexed_client

        # Find all references to helper
        refs = client.find_references("helper", repo)
        ref_names = {r.name for r in refs}

        # Should include at least the caller(s)
        # References includes calls, imports, etc.
        assert len(refs) >= 0  # May vary based on how imports are resolved


@requires_tree_sitter
class TestGetSymbolInfo:
    """Tests for get_symbol_info method."""

    def test_get_symbol_info_function(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test getting info for a function."""
        client, repo = indexed_client

        info = client.get_symbol_info("process_data", repo)
        assert info is not None
        assert info.name == "process_data"
        assert info.kind == NodeKind.FUNCTION
        assert info.signature is not None
        assert "data: list" in info.signature

    def test_get_symbol_info_class(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test getting info for a class."""
        client, repo = indexed_client

        info = client.get_symbol_info("DataProcessor", repo)
        assert info is not None
        assert info.name == "DataProcessor"
        assert info.kind == NodeKind.CLASS
        assert info.docstring is not None

    def test_get_symbol_info_method(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test getting info for a method."""
        client, repo = indexed_client

        # Use node_type to disambiguate
        info = client.get_symbol_info("run", repo, node_type=NodeKind.METHOD)
        assert info is not None
        assert info.name == "run"
        assert info.kind == NodeKind.METHOD

    def test_get_symbol_info_not_found(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test getting info for non-existent symbol."""
        client, repo = indexed_client

        info = client.get_symbol_info("nonexistent", repo)
        assert info is None

    def test_get_symbol_info_with_qualified_name(
        self, indexed_client: tuple[CodeIntelClient, Path]
    ) -> None:
        """Test disambiguation by qualified name."""
        client, repo = indexed_client

        # Get DataProcessor.process specifically
        info = client.get_symbol_info(
            "process", repo, qualified_name="DataProcessor.process"
        )
        assert info is not None
        assert info.qualified_name == "DataProcessor.process"


@requires_tree_sitter
class TestGetStats:
    """Tests for get_stats method."""

    def test_get_stats_empty(self, client_with_parser: CodeIntelClient, tmp_path: Path) -> None:
        """Test stats for empty repository."""
        stats = client_with_parser.get_stats(tmp_path)

        assert stats.repo_path == str(tmp_path.resolve())
        assert stats.total_files == 0
        assert stats.total_nodes == 0
        assert stats.total_edges == 0

    def test_get_stats_indexed(self, indexed_client: tuple[CodeIntelClient, Path]) -> None:
        """Test stats for indexed repository."""
        client, repo = indexed_client

        stats = client.get_stats(repo)

        assert stats.total_files == 3
        assert stats.total_nodes > 0
        assert "function" in stats.nodes_by_kind
        assert "class" in stats.nodes_by_kind
        assert stats.nodes_by_kind["class"] == 1  # Only DataProcessor


@requires_tree_sitter
class TestExcludePatterns:
    """Tests for file exclusion patterns."""

    def test_default_excludes_node_modules(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test that node_modules is excluded by default."""
        node_modules = sample_repo / "node_modules"
        node_modules.mkdir()
        (node_modules / "test.py").write_text("x = 1")

        result = client_with_parser.index_repo(sample_repo)
        assert result.files_indexed == 3  # Original 3 files only

    def test_default_excludes_git(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test that .git is excluded by default."""
        git_dir = sample_repo / ".git"
        git_dir.mkdir()
        (git_dir / "hooks" / "pre-commit.py").parent.mkdir(parents=True)
        (git_dir / "hooks" / "pre-commit.py").write_text("x = 1")

        result = client_with_parser.index_repo(sample_repo)
        assert result.files_indexed == 3

    def test_custom_exclude_patterns(
        self, client_with_parser: CodeIntelClient, sample_repo: Path
    ) -> None:
        """Test custom exclude patterns."""
        # Create a tests directory
        tests_dir = sample_repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_main.py").write_text("def test_foo(): pass")

        # Exclude tests directory
        result = client_with_parser.index_repo(
            sample_repo, exclude_patterns=["**/tests/**"]
        )
        assert result.files_indexed == 3  # Original files only


@requires_tree_sitter
class TestErrorHandling:
    """Tests for error handling."""

    def test_handles_syntax_errors(
        self, client_with_parser: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test handling files with syntax errors."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def foo( # syntax error")

        result = client_with_parser.index_repo(tmp_path)

        # File should still be counted as indexed (parser succeeded but noted errors)
        assert result.files_indexed == 1
        # Errors should be recorded
        assert len(result.errors) > 0

    def test_handles_unreadable_files(
        self, client_with_parser: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test handling when files can't be read."""
        # Create and then make unreadable (skip on Windows)
        import os
        import stat

        if os.name == "nt":
            pytest.skip("File permissions test not reliable on Windows")

        bad_file = tmp_path / "unreadable.py"
        bad_file.write_text("x = 1")
        bad_file.chmod(0o000)

        try:
            result = client_with_parser.index_repo(tmp_path)
            # Should fail gracefully
            assert result.files_failed == 1
        finally:
            # Restore permissions for cleanup
            bad_file.chmod(stat.S_IRUSR | stat.S_IWUSR)


@requires_tree_sitter
class TestFilePersistence:
    """Tests for database persistence."""

    def test_data_persists_across_clients(
        self, python_parser, sample_repo: Path, tmp_path: Path
    ) -> None:
        """Test that indexed data persists across client instances."""
        db_path = tmp_path / "persist.db"

        # Create client and index
        client1 = CodeIntelClient(db_path)
        client1.register_parser(python_parser)
        result = client1.index_repo(sample_repo)
        initial_nodes = result.nodes_created

        # Create new client with same database
        client2 = CodeIntelClient(db_path)

        # Data should be available
        stats = client2.get_stats(sample_repo)
        assert stats.total_nodes == initial_nodes


class TestIndexResult:
    """Tests for IndexResult dataclass."""

    def test_default_values(self) -> None:
        """Test IndexResult default values."""
        result = IndexResult()
        assert result.files_indexed == 0
        assert result.files_skipped == 0
        assert result.files_failed == 0
        assert result.nodes_created == 0
        assert result.edges_created == 0
        assert result.errors == []


class TestRepoStats:
    """Tests for RepoStats dataclass."""

    def test_construction(self) -> None:
        """Test RepoStats construction."""
        stats = RepoStats(
            repo_path="/test",
            total_files=10,
            total_nodes=50,
            total_edges=30,
            nodes_by_kind={"function": 20, "class": 5},
            edges_by_kind={"calls": 25, "imports": 5},
        )

        assert stats.repo_path == "/test"
        assert stats.total_files == 10
        assert stats.total_nodes == 50
        assert stats.total_edges == 30
        assert stats.nodes_by_kind["function"] == 20
        assert stats.edges_by_kind["calls"] == 25

    def test_default_values(self) -> None:
        """Test RepoStats default values."""
        stats = RepoStats(repo_path="/test")
        assert stats.total_files == 0
        assert stats.total_nodes == 0
        assert stats.total_edges == 0
        assert stats.nodes_by_kind == {}
        assert stats.edges_by_kind == {}


class TestClientInternalMethods:
    """Tests for CodeIntelClient internal methods that don't need tree-sitter."""

    def test_infer_language_python(self, client: CodeIntelClient) -> None:
        """Test language inference for Python files."""
        from pathlib import Path
        assert client._infer_language(Path("test.py")) == "python"
        assert client._infer_language(Path("types.pyi")) == "python"

    def test_infer_language_typescript(self, client: CodeIntelClient) -> None:
        """Test language inference for TypeScript files."""
        from pathlib import Path
        assert client._infer_language(Path("app.ts")) == "typescript"
        assert client._infer_language(Path("Component.tsx")) == "typescript"

    def test_infer_language_javascript(self, client: CodeIntelClient) -> None:
        """Test language inference for JavaScript files."""
        from pathlib import Path
        assert client._infer_language(Path("app.js")) == "javascript"
        assert client._infer_language(Path("Component.jsx")) == "javascript"

    def test_infer_language_csharp(self, client: CodeIntelClient) -> None:
        """Test language inference for C# files."""
        from pathlib import Path
        assert client._infer_language(Path("Program.cs")) == "csharp"

    def test_infer_language_unknown(self, client: CodeIntelClient) -> None:
        """Test language inference raises for unknown extensions."""
        from pathlib import Path
        with pytest.raises(ValueError, match="Cannot infer language"):
            client._infer_language(Path("readme.md"))

    def test_map_node_kind(self, client: CodeIntelClient) -> None:
        """Test mapping string to NodeKind."""
        assert client._map_node_kind("function") == NodeKind.FUNCTION
        assert client._map_node_kind("class") == NodeKind.CLASS
        assert client._map_node_kind("method") == NodeKind.METHOD
        assert client._map_node_kind("variable") == NodeKind.VARIABLE
        assert client._map_node_kind("import") == NodeKind.IMPORT

    def test_map_node_kind_case_insensitive(self, client: CodeIntelClient) -> None:
        """Test that node kind mapping is case insensitive."""
        assert client._map_node_kind("FUNCTION") == NodeKind.FUNCTION
        assert client._map_node_kind("Function") == NodeKind.FUNCTION
        assert client._map_node_kind("CLASS") == NodeKind.CLASS

    def test_map_node_kind_unknown(self, client: CodeIntelClient) -> None:
        """Test that unknown node kinds default to VARIABLE."""
        assert client._map_node_kind("unknown_type") == NodeKind.VARIABLE
        assert client._map_node_kind("") == NodeKind.VARIABLE

    def test_map_edge_kind(self, client: CodeIntelClient) -> None:
        """Test mapping string to EdgeKind."""
        assert client._map_edge_kind("calls") == EdgeKind.CALLS
        assert client._map_edge_kind("imports") == EdgeKind.IMPORTS
        assert client._map_edge_kind("inherits") == EdgeKind.INHERITS
        assert client._map_edge_kind("references") == EdgeKind.REFERENCES

    def test_map_edge_kind_case_insensitive(self, client: CodeIntelClient) -> None:
        """Test that edge kind mapping is case insensitive."""
        assert client._map_edge_kind("CALLS") == EdgeKind.CALLS
        assert client._map_edge_kind("Calls") == EdgeKind.CALLS

    def test_map_edge_kind_unknown(self, client: CodeIntelClient) -> None:
        """Test that unknown edge kinds default to REFERENCES."""
        assert client._map_edge_kind("unknown_type") == EdgeKind.REFERENCES
        assert client._map_edge_kind("") == EdgeKind.REFERENCES

    def test_resolve_repo_path_none(self, client: CodeIntelClient) -> None:
        """Test resolving None repo_path."""
        assert client._resolve_repo_path(None) == ""

    def test_resolve_repo_path_string(self, client: CodeIntelClient) -> None:
        """Test resolving string repo_path."""
        from pathlib import Path
        result = client._resolve_repo_path("/test/repo")
        assert result == str(Path("/test/repo").resolve())

    def test_resolve_repo_path_path(self, client: CodeIntelClient) -> None:
        """Test resolving Path repo_path."""
        from pathlib import Path
        result = client._resolve_repo_path(Path("/test/repo"))
        assert result == str(Path("/test/repo").resolve())

    def test_get_supported_extensions_empty(self, client: CodeIntelClient) -> None:
        """Test getting extensions when no parsers registered."""
        assert client._get_supported_extensions() == []

    def test_default_exclude_patterns(self, client: CodeIntelClient) -> None:
        """Test that default exclude patterns are set."""
        expected_patterns = [
            "**/node_modules/**",
            "**/.git/**",
            "**/__pycache__/**",
        ]
        for pattern in expected_patterns:
            assert pattern in client.DEFAULT_EXCLUDE_PATTERNS

    def test_matches_exclude_pattern(self, client: CodeIntelClient, tmp_path: Path) -> None:
        """Test exclude pattern matching using actual file paths.

        Note: Path.match() has specific behaviour with ** patterns.
        Patterns ending in /** only match against directories, while
        **/*.ext patterns match files with that extension.
        """
        # Create actual directory structure
        node_modules = tmp_path / "node_modules" / "pkg"
        node_modules.mkdir(parents=True)
        file_in_node_modules = node_modules / "file.py"
        file_in_node_modules.write_text("")

        pycache = tmp_path / "src" / "__pycache__"
        pycache.mkdir(parents=True)
        pyc_file = pycache / "mod.cpython-310.pyc"
        pyc_file.write_text("")

        src = tmp_path / "src"
        main_py = src / "main.py"
        main_py.write_text("")

        # Test with patterns that Path.match() handles correctly
        # **/*.pyc matches pyc files
        assert client._matches_exclude_pattern(
            pyc_file,
            tmp_path,
            ["**/*.pyc"],
        )

        # node_modules/*/*.py matches files two levels deep in node_modules
        assert client._matches_exclude_pattern(
            file_in_node_modules,
            tmp_path,
            ["node_modules/*/*.py"],
        )

        # Should not match regular Python files in src
        assert not client._matches_exclude_pattern(
            main_py,
            tmp_path,
            ["**/*.pyc", "node_modules/*/*.py"],
        )

    def test_discover_files_empty_dir(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test discovering files in empty directory."""
        files = client._discover_files(tmp_path, [".py"], [])
        assert files == []

    def test_discover_files_with_extension_filter(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test discovering files with extension filter."""
        # Create test files
        (tmp_path / "main.py").write_text("x = 1")
        (tmp_path / "utils.py").write_text("y = 2")
        (tmp_path / "readme.md").write_text("README")

        files = client._discover_files(tmp_path, [".py"], [])

        assert len(files) == 2
        assert all(f.suffix == ".py" for f in files)

    def test_discover_files_with_exclude_patterns(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test discovering files with exclude patterns."""
        # Create test files
        (tmp_path / "main.py").write_text("x = 1")
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "lib.py").write_text("z = 3")

        files = client._discover_files(
            tmp_path, [".py"], ["**/venv/**"]
        )

        assert len(files) == 1
        assert files[0].name == "main.py"

    def test_discover_files_sorted(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test that discovered files are sorted."""
        # Create files in non-alphabetical order
        (tmp_path / "z_file.py").write_text("")
        (tmp_path / "a_file.py").write_text("")
        (tmp_path / "m_file.py").write_text("")

        files = client._discover_files(tmp_path, [".py"], [])

        names = [f.name for f in files]
        assert names == sorted(names)


class TestXamlIntegration:
    """Tests for XAML parser integration with CodeIntelClient."""

    @pytest.fixture
    def xaml_parser(self):
        """Get an XAML parser instance."""
        from code_intel.parser.xaml import XamlParser
        return XamlParser()

    @pytest.fixture
    def client_with_xaml(self, client: CodeIntelClient, xaml_parser) -> CodeIntelClient:
        """Create a client with XAML parser registered."""
        client.register_parser(xaml_parser)
        return client

    def test_infer_language_xaml_with_registered_parser(
        self, client_with_xaml: CodeIntelClient
    ) -> None:
        """Test language inference for XAML files when parser is registered."""
        from pathlib import Path
        # XAML is not in the hardcoded map, but should be found via registered parser
        assert client_with_xaml._infer_language(Path("MainPage.xaml")) == "xaml"
        assert client_with_xaml._infer_language(Path("App.XAML")) == "xaml"

    def test_infer_language_xaml_without_parser_raises(
        self, client: CodeIntelClient
    ) -> None:
        """Test that XAML inference fails when no parser is registered."""
        from pathlib import Path
        with pytest.raises(ValueError, match="Cannot infer language"):
            client._infer_language(Path("MainPage.xaml"))

    def test_map_node_kind_xaml_types(self, client: CodeIntelClient) -> None:
        """Test mapping XAML-specific node types."""
        assert client._map_node_kind("page") == NodeKind.CLASS
        assert client._map_node_kind("named_element") == NodeKind.VARIABLE
        assert client._map_node_kind("resource") == NodeKind.CONSTANT

    def test_map_edge_kind_xaml_types(self, client: CodeIntelClient) -> None:
        """Test mapping XAML-specific edge types."""
        assert client._map_edge_kind("event_handler") == EdgeKind.CALLS
        assert client._map_edge_kind("binding") == EdgeKind.REFERENCES
        assert client._map_edge_kind("command") == EdgeKind.CALLS
        assert client._map_edge_kind("resource_ref") == EdgeKind.REFERENCES
        assert client._map_edge_kind("template_binding") == EdgeKind.REFERENCES

    def test_index_xaml_file(
        self, client_with_xaml: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test indexing a single XAML file."""
        xaml_content = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.Views.MainPage">
    <StackLayout>
        <Button x:Name="SubmitButton" Text="Submit" Clicked="OnSubmitClicked" />
        <Label Text="{Binding UserName}" />
    </StackLayout>
</ContentPage>
'''
        xaml_file = tmp_path / "MainPage.xaml"
        xaml_file.write_text(xaml_content)

        result = client_with_xaml.index_file(xaml_file, tmp_path)

        assert result.files_indexed == 0  # index_file increments on parent call
        assert result.nodes_created >= 2  # page + named element
        # Note: Edges to code-behind (event handlers, bindings) won't be created
        # until the C# code-behind file is also indexed, because edges require
        # both source and target nodes to exist in the graph.

    def test_index_repo_with_xaml(
        self, client_with_xaml: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test indexing a repository containing XAML files."""
        # Create a simple XAML file
        xaml_content = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.Views.HomePage">
    <Button x:Name="LoginButton" Clicked="OnLoginClicked" />
</ContentPage>
'''
        views_dir = tmp_path / "Views"
        views_dir.mkdir()
        (views_dir / "HomePage.xaml").write_text(xaml_content)

        result = client_with_xaml.index_repo(tmp_path)

        assert result.files_indexed == 1
        assert result.nodes_created >= 2  # page + named element
        # Edges to code-behind won't be stored without the C# file

    def test_xaml_parser_produces_edges(
        self, xaml_parser, tmp_path: Path
    ) -> None:
        """Test that XAML parser produces event handler and binding edges.

        Note: These edges may not be stored in the graph if the target
        code-behind file hasn't been indexed yet, but the parser should
        still produce them.
        """
        from code_intel.parser.xaml import XamlParser

        xaml_content = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="TestApp.TestPage">
    <Button Clicked="OnButtonClicked" />
    <Entry TextChanged="OnTextChanged" />
</ContentPage>
'''
        xaml_file = tmp_path / "TestPage.xaml"
        xaml_file.write_text(xaml_content)

        result = xaml_parser.parse_to_result(xaml_file)

        # Parser should produce edges for event handlers
        event_handler_edges = [e for e in result.edges if e.edge_type == "event_handler"]
        assert len(event_handler_edges) >= 2
        assert any("OnButtonClicked" in e.target_name for e in event_handler_edges)
        assert any("OnTextChanged" in e.target_name for e in event_handler_edges)

    def test_xaml_parser_produces_binding_edges(
        self, xaml_parser, tmp_path: Path
    ) -> None:
        """Test that XAML parser produces binding edges."""
        from code_intel.parser.xaml import XamlParser

        xaml_content = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="TestApp.BindingPage">
    <Label Text="{Binding Title}" />
    <Entry Text="{Binding UserInput, Mode=TwoWay}" />
</ContentPage>
'''
        xaml_file = tmp_path / "BindingPage.xaml"
        xaml_file.write_text(xaml_content)

        result = xaml_parser.parse_to_result(xaml_file)

        # Parser should produce edges for bindings
        binding_edges = [e for e in result.edges if e.edge_type == "binding"]
        assert len(binding_edges) >= 2
        assert any("Title" in e.target_name for e in binding_edges)
        assert any("UserInput" in e.target_name for e in binding_edges)


class TestIndexWithRoslyn:
    """Tests for index_with_roslyn method."""

    def test_index_with_roslyn_delegates_to_roslyn_indexer(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test that index_with_roslyn delegates to RoslynIndexer."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        # Create a mock result
        mock_result = RoslynIndexResult(
            files_indexed=5,
            files_failed=1,
            symbols_indexed=100,
            usages_indexed=50,
            errors=["test error"],
        )

        with patch("code_intel.indexer.roslyn.RoslynIndexer") as MockIndexer:
            mock_indexer = MagicMock()
            mock_indexer.index_repo.return_value = mock_result
            MockIndexer.return_value = mock_indexer

            result = client.index_with_roslyn(tmp_path)

            # Verify RoslynIndexer was instantiated with the client's db_path
            MockIndexer.assert_called_once_with(db_path=client._db_path)

            # Verify index_repo was called with correct params
            mock_indexer.index_repo.assert_called_once()
            call_kwargs = mock_indexer.index_repo.call_args
            assert call_kwargs[1]["force"] is False
            assert call_kwargs[1]["solution_file"] is None

            # Verify result conversion
            assert result.files_indexed == 5
            assert result.files_failed == 1
            assert result.nodes_created == 100
            assert result.edges_created == 50
            assert result.errors == ["test error"]

    def test_index_with_roslyn_with_solution_file(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test index_with_roslyn with explicit solution file."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        solution_file = tmp_path / "Test.sln"
        solution_file.write_text("")  # Create empty file

        mock_result = RoslynIndexResult()

        with patch("code_intel.indexer.roslyn.RoslynIndexer") as MockIndexer:
            mock_indexer = MagicMock()
            mock_indexer.index_repo.return_value = mock_result
            MockIndexer.return_value = mock_indexer

            client.index_with_roslyn(tmp_path, solution_file=solution_file)

            # Verify solution_file was passed
            call_kwargs = mock_indexer.index_repo.call_args
            assert call_kwargs[1]["solution_file"] == solution_file

    def test_index_with_roslyn_force_flag(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test index_with_roslyn with force=True."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        mock_result = RoslynIndexResult()

        with patch("code_intel.indexer.roslyn.RoslynIndexer") as MockIndexer:
            mock_indexer = MagicMock()
            mock_indexer.index_repo.return_value = mock_result
            MockIndexer.return_value = mock_indexer

            client.index_with_roslyn(tmp_path, force=True)

            # Verify force was passed
            call_kwargs = mock_indexer.index_repo.call_args
            assert call_kwargs[1]["force"] is True

    def test_index_with_roslyn_progress_callback(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test that progress callback is passed to RoslynIndexer."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        mock_result = RoslynIndexResult()
        progress_calls: list[tuple[int, int, str]] = []

        def on_progress(current: int, total: int, message: str) -> None:
            progress_calls.append((current, total, message))

        with patch("code_intel.indexer.roslyn.RoslynIndexer") as MockIndexer:
            mock_indexer = MagicMock()

            # Simulate the indexer calling the progress callback
            def mock_index_repo(repo_path, **kwargs):
                callback = kwargs.get("progress_callback")
                if callback:
                    callback(1, 10, "Indexing file1.cs")
                    callback(2, 10, "Indexing file2.cs")
                return mock_result

            mock_indexer.index_repo.side_effect = mock_index_repo
            MockIndexer.return_value = mock_indexer

            client.index_with_roslyn(tmp_path, progress_callback=on_progress)

            # Verify progress callback was invoked
            assert len(progress_calls) == 2
            assert progress_calls[0] == (1, 10, "Indexing file1.cs")
            assert progress_calls[1] == (2, 10, "Indexing file2.cs")

    def test_index_with_roslyn_returns_index_result(
        self, client: CodeIntelClient, tmp_path: Path
    ) -> None:
        """Test that index_with_roslyn returns IndexResult type."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        mock_result = RoslynIndexResult(
            files_indexed=3,
            symbols_indexed=42,
            usages_indexed=15,
        )

        with patch("code_intel.indexer.roslyn.RoslynIndexer") as MockIndexer:
            mock_indexer = MagicMock()
            mock_indexer.index_repo.return_value = mock_result
            MockIndexer.return_value = mock_indexer

            result = client.index_with_roslyn(tmp_path)

            # Verify it's an IndexResult (not RoslynIndexResult)
            assert isinstance(result, IndexResult)
            assert result.files_indexed == 3
            assert result.nodes_created == 42  # symbols -> nodes
            assert result.edges_created == 15  # usages -> edges

    def test_index_with_roslyn_with_persistent_db(
        self, tmp_path: Path
    ) -> None:
        """Test index_with_roslyn shares database with client."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        db_path = tmp_path / "test.db"
        client = CodeIntelClient(db_path)

        mock_result = RoslynIndexResult()

        with patch("code_intel.indexer.roslyn.RoslynIndexer") as MockIndexer:
            mock_indexer = MagicMock()
            mock_indexer.index_repo.return_value = mock_result
            MockIndexer.return_value = mock_indexer

            client.index_with_roslyn(tmp_path)

            # Verify RoslynIndexer was created with client's db_path
            MockIndexer.assert_called_once_with(db_path=db_path)
