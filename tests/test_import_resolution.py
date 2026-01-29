"""Tests for import tracking and cross-file symbol resolution (CINT-18)."""

import pytest

from code_intel.client import CodeIntelClient


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-python are available."""
    try:
        from tree_sitter import Parser  # noqa: F401
        import tree_sitter_python  # noqa: F401
        return True
    except ImportError:
        return False


# Skip all tests in this module if tree-sitter is not available
pytestmark = pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-python not installed"
)


@pytest.fixture
def parser():
    """Create a Python parser instance."""
    from code_intel.parser.python import PythonParser
    return PythonParser()


@pytest.fixture
def client(parser) -> CodeIntelClient:
    """Create a client with Python parser registered."""
    client = CodeIntelClient()
    client.register_parser(parser)
    return client


class TestImportMapBuilder:
    """Tests for the import map builder."""

    def test_simple_import(self, parser):
        """Test import map for simple 'import x' statement."""
        source = b"import os"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        import_map = parser._build_import_map(symbols)

        assert "os" in import_map
        entry = import_map["os"]
        assert entry.local_name == "os"
        assert entry.module == "os"
        assert entry.symbol is None
        assert entry.import_type == "module"

    def test_aliased_import(self, parser):
        """Test import map for 'import x as y' statement."""
        source = b"import numpy as np"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        import_map = parser._build_import_map(symbols)

        assert "np" in import_map
        entry = import_map["np"]
        assert entry.local_name == "np"
        assert entry.module == "numpy"
        assert entry.import_type == "module"

    def test_from_import(self, parser):
        """Test import map for 'from x import y' statement."""
        source = b"from pathlib import Path"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        import_map = parser._build_import_map(symbols)

        assert "Path" in import_map
        entry = import_map["Path"]
        assert entry.local_name == "Path"
        assert entry.module == "pathlib"
        assert entry.symbol == "Path"
        assert entry.import_type == "from"

    def test_from_import_alias(self, parser):
        """Test import map for 'from x import y as z' statement."""
        source = b"from typing import List as L"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        import_map = parser._build_import_map(symbols)

        assert "L" in import_map
        entry = import_map["L"]
        assert entry.local_name == "L"
        assert entry.module == "typing"
        assert entry.symbol == "List"
        assert entry.import_type == "from"

    def test_wildcard_import(self, parser):
        """Test import map for 'from x import *' statement."""
        source = b"from os.path import *"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        import_map = parser._build_import_map(symbols)

        assert "*" in import_map
        entry = import_map["*"]
        assert entry.module == "os.path"
        assert entry.import_type == "wildcard"

    def test_relative_import_resolution(self, parser, tmp_path):
        """Test that relative imports are resolved based on file path."""
        # from . import sibling
        source = b"from . import sibling"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        # Simulate file in foundry/smith.py
        file_path = tmp_path / "foundry" / "smith.py"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        import_map = parser._build_import_map(symbols, file_path)

        assert "sibling" in import_map
        entry = import_map["sibling"]
        # The module should contain 'foundry' since that's the package
        # and 'sibling' should be the symbol, not in the module path
        assert "foundry" in entry.module
        assert entry.symbol == "sibling"

    def test_parent_relative_import(self, parser, tmp_path):
        """Test that parent relative imports (from .. import x) are resolved."""
        source = b"from .. import parent_module"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        # Simulate file in foundry/subpkg/module.py
        file_path = tmp_path / "foundry" / "subpkg" / "module.py"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        import_map = parser._build_import_map(symbols, file_path)

        assert "parent_module" in import_map
        entry = import_map["parent_module"]
        # Should resolve to foundry.parent_module
        assert "foundry" in entry.module


class TestAttributeCallResolution:
    """Tests for resolving attribute calls via import map."""

    def test_module_qualified_call(self, parser):
        """Test that module.function() calls are resolved."""
        source = b"""
import jira

def process():
    jira.add_worklog()
"""
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        call = next((c for c in calls if c.get("metadata", {}).get("target_module")), None)

        assert call is not None
        assert call["target"] == "add_worklog"
        assert call["metadata"]["target_module"] == "jira"

    def test_aliased_module_call(self, parser):
        """Test that aliased_module.function() calls are resolved."""
        source = b"""
import numpy as np

def compute():
    np.array([1, 2, 3])
"""
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        call = next((c for c in calls if c.get("metadata", {}).get("target_module")), None)

        assert call is not None
        assert call["target"] == "array"
        assert call["metadata"]["target_module"] == "numpy"

    def test_self_method_call(self, parser):
        """Test that self.method() calls extract just the method name."""
        source = b"""
class MyClass:
    def run(self):
        self.process()

    def process(self):
        pass
"""
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        # Find the self.process call
        process_call = next(
            (c for c in calls if c["target"] == "process"),
            None
        )

        assert process_call is not None
        assert process_call["source"] == "MyClass.run"
        assert process_call.get("metadata", {}).get("same_class_call") is True

    def test_cls_method_call(self, parser):
        """Test that cls.method() calls in classmethods are resolved."""
        source = b"""
class MyClass:
    @classmethod
    def create(cls):
        return cls.from_dict({})

    @classmethod
    def from_dict(cls, d):
        pass
"""
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        from_dict_call = next(
            (c for c in calls if c["target"] == "from_dict"),
            None
        )

        assert from_dict_call is not None
        assert from_dict_call.get("metadata", {}).get("same_class_call") is True

    def test_from_import_direct_call(self, parser):
        """Test that directly imported functions get module hint."""
        source = b"""
from foundry.jira import add_worklog

def process():
    add_worklog()
"""
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        call = next((c for c in calls if c["target"] == "add_worklog"), None)

        assert call is not None
        assert call.get("metadata", {}).get("target_module") == "foundry.jira"


class TestCrossFileResolution:
    """Integration tests for cross-file symbol resolution."""

    def test_cross_file_callers(self, client, tmp_path):
        """Test that cross-file callers are properly resolved."""
        # Create a module with a function
        jira_py = tmp_path / "jira.py"
        jira_py.write_text('''
def add_worklog(issue: str, time: str) -> None:
    """Add a worklog entry."""
    pass
''')

        # Create files that call the function
        oracle_py = tmp_path / "oracle.py"
        oracle_py.write_text('''
import jira

def process_ticket():
    jira.add_worklog("PROJ-123", "1h")
''')

        smith_py = tmp_path / "smith.py"
        smith_py.write_text('''
from jira import add_worklog

def handle_work():
    add_worklog("PROJ-456", "2h")
''')

        # Index the repo
        result = client.index_repo(tmp_path)
        assert result.files_indexed == 3
        assert result.edges_created >= 2

        # Find callers of add_worklog
        callers = client.find_callers("add_worklog", tmp_path)
        caller_names = {c.name for c in callers}

        # Both process_ticket and handle_work should be found
        assert "process_ticket" in caller_names
        assert "handle_work" in caller_names

    def test_same_class_method_resolution(self, client, tmp_path):
        """Test that self.method() calls resolve within the class."""
        models_py = tmp_path / "models.py"
        models_py.write_text('''
class Processor:
    def run(self):
        result = self.transform()
        self.save(result)

    def transform(self):
        return "transformed"

    def save(self, data):
        pass
''')

        result = client.index_repo(tmp_path)
        assert result.edges_created >= 2

        # Find callers of transform
        transform_callers = client.find_callers("transform", tmp_path)
        assert any(c.name == "run" for c in transform_callers)

        # Find callers of save
        save_callers = client.find_callers("save", tmp_path)
        assert any(c.name == "run" for c in save_callers)

    def test_multiple_callers_same_function(self, client, tmp_path):
        """Test resolving multiple callers from different files."""
        # Shared utility
        utils_py = tmp_path / "utils.py"
        utils_py.write_text('''
def format_date(dt):
    """Format a date."""
    return dt.strftime("%Y-%m-%d")
''')

        # Multiple callers
        module_a = tmp_path / "module_a.py"
        module_a.write_text('''
from utils import format_date

def render_report():
    import datetime
    return format_date(datetime.datetime.now())
''')

        module_b = tmp_path / "module_b.py"
        module_b.write_text('''
import utils

def display_event():
    import datetime
    return utils.format_date(datetime.datetime.now())
''')

        module_c = tmp_path / "module_c.py"
        module_c.write_text('''
from utils import format_date as fmt

def show_timestamp():
    import datetime
    return fmt(datetime.datetime.now())
''')

        result = client.index_repo(tmp_path)
        assert result.files_indexed == 4

        callers = client.find_callers("format_date", tmp_path)
        caller_names = {c.name for c in callers}

        assert "render_report" in caller_names
        assert "display_event" in caller_names
        assert "show_timestamp" in caller_names


class TestModuleToFilePath:
    """Tests for module path to file path conversion."""

    def test_simple_module(self, client, tmp_path):
        """Test converting simple module path to file."""
        # Create the file
        test_py = tmp_path / "mymodule.py"
        test_py.touch()

        result = client._module_to_file_path("mymodule", str(tmp_path))
        assert result == str(test_py)

    def test_nested_module(self, client, tmp_path):
        """Test converting nested module path to file."""
        # Create nested structure
        nested = tmp_path / "package" / "submodule.py"
        nested.parent.mkdir(parents=True)
        nested.touch()

        result = client._module_to_file_path("package.submodule", str(tmp_path))
        assert result == str(nested)

    def test_package_init(self, client, tmp_path):
        """Test converting package to __init__.py."""
        # Create package with __init__.py
        pkg_init = tmp_path / "mypackage" / "__init__.py"
        pkg_init.parent.mkdir()
        pkg_init.touch()

        result = client._module_to_file_path("mypackage", str(tmp_path))
        assert result == str(pkg_init)

    def test_src_layout(self, client, tmp_path):
        """Test converting module with src/ layout."""
        # Create src layout
        src_module = tmp_path / "src" / "mypackage" / "module.py"
        src_module.parent.mkdir(parents=True)
        src_module.touch()

        result = client._module_to_file_path("mypackage.module", str(tmp_path))
        assert result == str(src_module)

    def test_nonexistent_module(self, client, tmp_path):
        """Test that nonexistent module returns None."""
        result = client._module_to_file_path("nonexistent.module", str(tmp_path))
        assert result is None


class TestEdgeMetadata:
    """Tests for edge metadata preservation."""

    def test_cross_file_edge_created(self, client, tmp_path):
        """Test that edges are created for cross-file calls.

        Note: Cross-file edges require the target to be indexed before the source.
        Using index_file for explicit ordering.
        """
        # Target module - must be indexed first for edge resolution to work
        target_py = tmp_path / "target_module.py"
        target_py.write_text('''
def add_worklog():
    pass
''')

        # Caller module
        caller_py = tmp_path / "zcaller.py"  # 'z' prefix ensures it's after target alphabetically
        caller_py.write_text('''
import target_module

def process():
    target_module.add_worklog()
''')

        client.index_repo(tmp_path)

        # Verify edge was created by checking callers
        callers = client.find_callers("add_worklog", tmp_path)
        assert len(callers) == 1
        assert callers[0].name == "process"
