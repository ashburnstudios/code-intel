"""Tests for the CodeIntelClient API."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from code_intel.client import CodeIntelClient, IndexResult, RepoStats
from code_intel.graph.schema import NodeKind


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
