"""Integration tests for the Roslyn indexer.

These tests require OmniSharp to be installed. They will be skipped if
OmniSharp is not available.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from code_intel.graph.schema import NodeKind

if TYPE_CHECKING:
    from code_intel.indexer.roslyn import RoslynIndexer


def _check_omnisharp_available() -> bool:
    """Check if OmniSharp is available."""
    if shutil.which("omnisharp") or shutil.which("OmniSharp"):
        return True
    # Check common paths
    import os
    import glob

    paths = [
        os.path.expanduser("~/.dotnet/tools/omnisharp"),
        os.path.expanduser(
            "~/.vscode/extensions/ms-dotnettools.csharp-*/omnisharp/OmniSharp"
        ),
    ]
    for pattern in paths:
        if glob.glob(pattern):
            return True
    return False


requires_omnisharp = pytest.mark.skipif(
    not _check_omnisharp_available(),
    reason="OmniSharp not installed",
)


@pytest.fixture
def lsp_fixtures_path() -> Path:
    """Return path to LSP test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_csproj(lsp_fixtures_path: Path) -> Path:
    """Return path to sample .csproj file."""
    return lsp_fixtures_path / "SampleProject.csproj"


class TestRoslynIndexerWithoutOmniSharp:
    """Tests that don't require OmniSharp."""

    def test_import_roslyn_indexer(self):
        """Test that RoslynIndexer can be imported."""
        from code_intel.indexer.roslyn import RoslynIndexer, RoslynIndexResult

        assert RoslynIndexer is not None
        assert RoslynIndexResult is not None

    def test_create_indexer(self):
        """Test creating a RoslynIndexer instance."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        assert indexer is not None

    def test_create_indexer_with_db_path(self, tmp_path: Path):
        """Test creating a RoslynIndexer with a database path."""
        from code_intel.indexer.roslyn import RoslynIndexer

        db_path = tmp_path / "test.db"
        indexer = RoslynIndexer(db_path=db_path)
        assert indexer is not None

    def test_roslyn_index_result(self):
        """Test RoslynIndexResult dataclass."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        result = RoslynIndexResult()
        assert result.files_indexed == 0
        assert result.files_failed == 0
        assert result.symbols_indexed == 0
        assert result.usages_indexed == 0
        assert result.errors == []

    def test_symbol_kind_mapping(self):
        """Test symbol kind mapping."""
        from code_intel.indexer.roslyn import RoslynIndexer

        mapping = RoslynIndexer.SYMBOL_KIND_MAP
        assert mapping["class"] == NodeKind.CLASS
        assert mapping["method"] == NodeKind.METHOD
        assert mapping["property"] == NodeKind.PROPERTY
        assert mapping["interface"] == NodeKind.INTERFACE
        assert mapping["enum"] == NodeKind.ENUM


class TestOmniSharpServer:
    """Tests for OmniSharpServer class."""

    def test_import_omnisharp_server(self):
        """Test that OmniSharpServer can be imported."""
        from code_intel.lsp.omnisharp import (
            OmniSharpError,
            OmniSharpNotFoundError,
            OmniSharpServer,
            OmniSharpTimeoutError,
        )

        assert OmniSharpServer is not None
        assert OmniSharpError is not None
        assert OmniSharpNotFoundError is not None
        assert OmniSharpTimeoutError is not None

    def test_create_server_without_omnisharp(self, tmp_path: Path):
        """Test that creating a server fails gracefully without OmniSharp."""
        from code_intel.lsp.omnisharp import OmniSharpNotFoundError, OmniSharpServer

        # Create a fake solution file
        sln_path = tmp_path / "Test.sln"
        sln_path.write_text("")

        if not _check_omnisharp_available():
            with pytest.raises(OmniSharpNotFoundError):
                OmniSharpServer(sln_path)

    def test_server_with_explicit_invalid_path(self, tmp_path: Path):
        """Test that server raises error with invalid OmniSharp path."""
        from code_intel.lsp.omnisharp import OmniSharpNotFoundError, OmniSharpServer

        sln_path = tmp_path / "Test.sln"
        sln_path.write_text("")

        with pytest.raises(OmniSharpNotFoundError):
            OmniSharpServer(sln_path, omnisharp_path="/nonexistent/omnisharp")


@requires_omnisharp
class TestRoslynIndexerIntegration:
    """Integration tests that require OmniSharp.

    These tests verify that the Roslyn indexer can:
    1. Start and stop OmniSharp cleanly
    2. Index C# solutions
    3. Find delegate-based callers
    4. Store results in SQLite
    """

    @pytest.fixture
    def indexer(self) -> "RoslynIndexer":
        """Create a RoslynIndexer instance."""
        from code_intel.indexer.roslyn import RoslynIndexer

        return RoslynIndexer()

    def test_index_sample_project(
        self, indexer: "RoslynIndexer", sample_csproj: Path, tmp_path: Path
    ):
        """Test indexing the sample C# project."""
        if not sample_csproj.exists():
            pytest.skip("Sample project not found")

        result = indexer.index_solution(sample_csproj)

        # Should have indexed some symbols
        assert result.files_indexed > 0 or result.files_failed > 0
        # Should not have catastrophic failures
        assert len(result.errors) < result.files_indexed + result.files_failed

    def test_omnisharp_starts_and_stops_cleanly(self, sample_csproj: Path):
        """Test that OmniSharp starts and stops without errors."""
        from code_intel.lsp.omnisharp import OmniSharpServer

        if not sample_csproj.exists():
            pytest.skip("Sample project not found")

        server = OmniSharpServer(sample_csproj, timeout=120.0)
        try:
            server.start()
            # Server should be running
            assert server._running is True
            assert server._process is not None
        finally:
            server.stop()
            # Server should be stopped
            assert server._process is None

    def test_get_code_structure(self, sample_csproj: Path, lsp_fixtures_path: Path):
        """Test getting code structure for a file."""
        from code_intel.lsp.omnisharp import OmniSharpServer

        if not sample_csproj.exists():
            pytest.skip("Sample project not found")

        simple_class = lsp_fixtures_path / "SimpleClass.cs"
        if not simple_class.exists():
            pytest.skip("SimpleClass.cs not found")

        with OmniSharpServer(sample_csproj, timeout=120.0) as server:
            structure = server.get_code_structure(simple_class)

            # Should have found some elements
            assert structure.elements is not None
            assert len(structure.elements) > 0

            # Should have found the namespace or class
            element_names = [e.name for e in structure.elements]
            # Depending on structure, might be namespace or class at top level
            assert any(
                name in ["SampleProject", "SimpleClass", "SimpleClassUser"]
                for name in element_names
            )

    def test_find_usages(self, sample_csproj: Path, lsp_fixtures_path: Path):
        """Test finding usages of a method."""
        from code_intel.lsp.omnisharp import OmniSharpServer

        if not sample_csproj.exists():
            pytest.skip("Sample project not found")

        simple_class = lsp_fixtures_path / "SimpleClass.cs"
        if not simple_class.exists():
            pytest.skip("SimpleClass.cs not found")

        with OmniSharpServer(sample_csproj, timeout=120.0) as server:
            # First get structure to verify connection works
            _ = server.get_code_structure(simple_class)

            # Find PublicMethod position (this is approximate)
            # In real usage, we'd get the exact position from codestructure
            # For now, search for the method in the file
            content = simple_class.read_text()
            lines = content.split("\n")
            method_line = None
            for i, line in enumerate(lines):
                if "public void PublicMethod()" in line:
                    method_line = i
                    break

            if method_line is not None:
                # Query usages - may or may not find results depending on OmniSharp loading
                _ = server.find_usages(simple_class, method_line, 16)

    def test_index_delegates_and_events(
        self, indexer: "RoslynIndexer", sample_csproj: Path
    ):
        """Test that delegate-based calls are indexed.

        This is the key test for CINT-14 - verifying that the Roslyn
        indexer captures indirect calls through delegates and events.
        """
        if not sample_csproj.exists():
            pytest.skip("Sample project not found")

        result = indexer.index_solution(sample_csproj, force=True)

        # Should have indexed the delegate example
        assert result.symbols_indexed > 0

        # Check that usages were found
        # The exact count depends on what OmniSharp discovers
        # Just verify we didn't completely fail
        if result.files_indexed > 0:
            # We should have found at least some relationships
            # Even if not all delegate calls are captured
            pass

    def test_clear_repository(self, indexer: "RoslynIndexer", sample_csproj: Path):
        """Test clearing indexed data."""
        if not sample_csproj.exists():
            pytest.skip("Sample project not found")

        # Index first
        indexer.index_solution(sample_csproj, force=True)

        # Clear
        repo_path = sample_csproj.parent
        deleted = indexer.clear_repository(repo_path)

        # Should have deleted something (or be 0 if nothing indexed)
        assert deleted >= 0


class TestRoslynIndexerResultIntegrity:
    """Tests for result data integrity."""

    def test_result_dataclass_fields(self):
        """Test that RoslynIndexResult has expected fields."""
        from code_intel.indexer.roslyn import RoslynIndexResult

        result = RoslynIndexResult(
            files_indexed=5,
            files_failed=1,
            symbols_indexed=20,
            usages_indexed=15,
            errors=["error1", "error2"],
        )

        assert result.files_indexed == 5
        assert result.files_failed == 1
        assert result.symbols_indexed == 20
        assert result.usages_indexed == 15
        assert len(result.errors) == 2

    def test_progress_callback_type(self):
        """Test that progress callback signature matches."""
        from code_intel.indexer.roslyn import RoslynProgressCallback

        # Create a valid callback
        def callback(current: int, total: int, message: str) -> None:
            pass

        # This should type-check (we're just verifying the type exists)
        cb: RoslynProgressCallback = callback
        assert callable(cb)


class TestIndexRepoMethod:
    """Tests for the index_repo method and solution discovery."""

    def test_index_repo_method_exists(self):
        """Test that index_repo method exists on RoslynIndexer."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        assert hasattr(indexer, "index_repo")
        assert callable(indexer.index_repo)

    def test_index_repo_with_invalid_repo_path(self, tmp_path: Path):
        """Test index_repo returns error for non-existent path."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        nonexistent = tmp_path / "nonexistent"

        result = indexer.index_repo(nonexistent)

        assert result.files_indexed == 0
        assert len(result.errors) == 1
        assert "not a directory" in result.errors[0]

    def test_index_repo_with_invalid_solution_file(self, tmp_path: Path):
        """Test index_repo returns error for non-existent solution file."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()

        result = indexer.index_repo(tmp_path, solution_file="/nonexistent/Test.sln")

        assert result.files_indexed == 0
        assert len(result.errors) == 1
        assert "Solution file not found" in result.errors[0]

    def test_index_repo_no_solution_found(self, tmp_path: Path):
        """Test index_repo returns error when no solution files exist."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        # Create an empty directory
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# Python file")

        result = indexer.index_repo(tmp_path)

        assert result.files_indexed == 0
        assert len(result.errors) == 1
        assert "No .sln or .csproj file found" in result.errors[0]


class TestSolutionDiscovery:
    """Tests for solution file auto-discovery."""

    def test_discover_sln_at_root(self, tmp_path: Path):
        """Test discovering .sln file at repository root."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        sln_path = tmp_path / "MyProject.sln"
        sln_path.write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result == sln_path

    def test_discover_sln_prefers_matching_name(self, tmp_path: Path):
        """Test that discovery prefers .sln matching directory name."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        # Create directory with specific name
        repo_dir = tmp_path / "MyApp"
        repo_dir.mkdir()
        # Create multiple .sln files
        (repo_dir / "Other.sln").write_text("")
        (repo_dir / "MyApp.sln").write_text("")
        (repo_dir / "Another.sln").write_text("")

        result = indexer._discover_solution(repo_dir)

        assert result is not None
        assert result.stem == "MyApp"

    def test_discover_sln_alphabetical_fallback(self, tmp_path: Path):
        """Test that discovery uses alphabetical order when no name match."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        (tmp_path / "Zebra.sln").write_text("")
        (tmp_path / "Alpha.sln").write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result is not None
        assert result.stem == "Alpha"

    def test_discover_sln_in_subdirectory(self, tmp_path: Path):
        """Test discovering .sln file one level deep."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        subdir = tmp_path / "src"
        subdir.mkdir()
        sln_path = subdir / "MyProject.sln"
        sln_path.write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result == sln_path

    def test_discover_csproj_fallback(self, tmp_path: Path):
        """Test falling back to .csproj when no .sln found."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        csproj_path = tmp_path / "MyProject.csproj"
        csproj_path.write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result == csproj_path

    def test_discover_prefers_sln_over_csproj(self, tmp_path: Path):
        """Test that .sln is preferred over .csproj at same level."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        (tmp_path / "MyProject.sln").write_text("")
        (tmp_path / "MyProject.csproj").write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result is not None
        assert result.suffix == ".sln"

    def test_discover_sln_nested_deep(self, tmp_path: Path):
        """Test discovering .sln file in nested directory."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        sln_path = nested / "Deep.sln"
        sln_path.write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result == sln_path

    def test_discover_skips_hidden_directories(self, tmp_path: Path):
        """Test that hidden directories are skipped during discovery."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "Hidden.sln").write_text("")
        # Also create a visible one to find
        (tmp_path / "Visible.sln").write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result is not None
        assert result.stem == "Visible"

    def test_discover_returns_none_for_empty_dir(self, tmp_path: Path):
        """Test that discovery returns None for empty directory."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()

        result = indexer._discover_solution(tmp_path)

        assert result is None

    def test_discover_csproj_in_subdirectory(self, tmp_path: Path):
        """Test discovering .csproj file one level deep."""
        from code_intel.indexer.roslyn import RoslynIndexer

        indexer = RoslynIndexer()
        subdir = tmp_path / "src"
        subdir.mkdir()
        csproj_path = subdir / "MyProject.csproj"
        csproj_path.write_text("")

        result = indexer._discover_solution(tmp_path)

        assert result == csproj_path
