"""Tests for the Python parser."""

import pytest
from pathlib import Path

from code_intel.parser.python import PythonParser


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-python are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_python
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
    return PythonParser()


class TestPythonParserProperties:
    """Tests for parser properties."""

    def test_language_name(self, parser: PythonParser):
        """Test language name property."""
        assert parser.language_name == "python"

    def test_file_extensions(self, parser: PythonParser):
        """Test file extensions property."""
        assert ".py" in parser.file_extensions
        assert ".pyi" in parser.file_extensions


class TestFunctionExtraction:
    """Tests for function definition extraction."""

    def test_simple_function(self, parser: PythonParser):
        """Test extracting a simple function."""
        source = b'''
def hello():
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "hello"
        assert funcs[0]["signature"] == "def hello()"

    def test_function_with_params(self, parser: PythonParser):
        """Test extracting function with parameters."""
        source = b'''
def greet(name: str, age: int = 0) -> str:
    return f"Hello {name}"
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "greet"
        assert "name: str" in funcs[0]["signature"]
        assert "-> str" in funcs[0]["signature"]

    def test_function_with_docstring(self, parser: PythonParser):
        """Test extracting function docstring."""
        source = b'''
def documented():
    """This is a docstring."""
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 1
        assert funcs[0]["docstring"] == "This is a docstring."

    def test_async_function(self, parser: PythonParser):
        """Test extracting async function."""
        source = b'''
async def fetch_data():
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "fetch_data"
        assert funcs[0]["metadata"].get("async") is True
        assert "async" in funcs[0]["signature"]

    def test_decorated_function(self, parser: PythonParser):
        """Test extracting decorated function."""
        source = b'''
@decorator
@another(arg=1)
def decorated_func():
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "decorated_func"
        decorators = funcs[0]["metadata"].get("decorators", [])
        assert "decorator" in decorators
        assert "another(arg=1)" in decorators

    def test_multiple_functions(self, parser: PythonParser):
        """Test extracting multiple functions."""
        source = b'''
def first():
    pass

def second():
    pass

def third():
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 3
        names = [f["name"] for f in funcs]
        assert names == ["first", "second", "third"]


class TestClassExtraction:
    """Tests for class definition extraction."""

    def test_simple_class(self, parser: PythonParser):
        """Test extracting a simple class."""
        source = b'''
class MyClass:
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "MyClass"

    def test_class_with_docstring(self, parser: PythonParser):
        """Test extracting class docstring."""
        source = b'''
class Documented:
    """Class documentation."""
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["docstring"] == "Class documentation."

    def test_class_inheritance(self, parser: PythonParser):
        """Test extracting class with base classes."""
        source = b'''
class Child(Parent):
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "Child"
        bases = classes[0]["metadata"].get("bases", [])
        assert "Parent" in bases

    def test_multiple_inheritance(self, parser: PythonParser):
        """Test extracting class with multiple base classes."""
        source = b'''
class Multi(Base1, Base2, mixin.Mixin):
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        bases = classes[0]["metadata"].get("bases", [])
        assert "Base1" in bases
        assert "Base2" in bases
        assert "mixin.Mixin" in bases

    def test_decorated_class(self, parser: PythonParser):
        """Test extracting decorated class."""
        source = b'''
@dataclass
class DataClass:
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        decorators = classes[0]["metadata"].get("decorators", [])
        assert "dataclass" in decorators


class TestMethodExtraction:
    """Tests for method extraction within classes."""

    def test_class_methods(self, parser: PythonParser):
        """Test extracting methods from a class."""
        source = b'''
class MyClass:
    def method_one(self):
        pass

    def method_two(self, arg):
        pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 2
        assert methods[0]["name"] == "method_one"
        assert methods[1]["name"] == "method_two"

        # Check qualified names
        assert methods[0]["qualified_name"] == "MyClass.method_one"
        assert methods[1]["qualified_name"] == "MyClass.method_two"

    def test_special_methods(self, parser: PythonParser):
        """Test extracting special methods."""
        source = b'''
class MyClass:
    def __init__(self):
        pass

    def __str__(self):
        return ""
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        names = [m["name"] for m in methods]
        assert "__init__" in names
        assert "__str__" in names

    def test_decorated_method(self, parser: PythonParser):
        """Test extracting decorated methods."""
        source = b'''
class MyClass:
    @staticmethod
    def static_method():
        pass

    @classmethod
    def class_method(cls):
        pass

    @property
    def my_property(self):
        return self._value
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 3

        static = next(m for m in methods if m["name"] == "static_method")
        assert "staticmethod" in static["metadata"].get("decorators", [])

        classm = next(m for m in methods if m["name"] == "class_method")
        assert "classmethod" in classm["metadata"].get("decorators", [])

        prop = next(m for m in methods if m["name"] == "my_property")
        assert "property" in prop["metadata"].get("decorators", [])


class TestVariableExtraction:
    """Tests for module-level variable extraction."""

    def test_simple_assignment(self, parser: PythonParser):
        """Test extracting simple variable assignment."""
        source = b'''
MY_CONSTANT = 42
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        vars = [s for s in symbols if s["kind"] == "variable"]
        assert len(vars) == 1
        assert vars[0]["name"] == "MY_CONSTANT"

    def test_multiple_variables(self, parser: PythonParser):
        """Test extracting multiple variables."""
        source = b'''
FOO = 1
BAR = 2
BAZ = 3
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        vars = [s for s in symbols if s["kind"] == "variable"]
        assert len(vars) == 3
        names = [v["name"] for v in vars]
        assert "FOO" in names
        assert "BAR" in names
        assert "BAZ" in names

    def test_tuple_unpacking(self, parser: PythonParser):
        """Test extracting variables from tuple unpacking."""
        source = b'''
a, b = 1, 2
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        vars = [s for s in symbols if s["kind"] == "variable"]
        names = [v["name"] for v in vars]
        assert "a" in names
        assert "b" in names


class TestImportExtraction:
    """Tests for import statement extraction."""

    def test_simple_import(self, parser: PythonParser):
        """Test extracting simple import."""
        source = b'''
import os
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "os"
        assert imports[0]["metadata"]["import_type"] == "module"

    def test_dotted_import(self, parser: PythonParser):
        """Test extracting dotted import."""
        source = b'''
import os.path
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "os.path"

    def test_aliased_import(self, parser: PythonParser):
        """Test extracting aliased import."""
        source = b'''
import numpy as np
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "np"  # Uses alias as name
        assert imports[0]["metadata"]["alias"] == "np"
        assert imports[0]["metadata"]["original_name"] == "numpy"

    def test_from_import(self, parser: PythonParser):
        """Test extracting from import."""
        source = b'''
from pathlib import Path
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "Path"
        assert imports[0]["qualified_name"] == "pathlib.Path"
        assert imports[0]["metadata"]["import_type"] == "from"
        assert imports[0]["metadata"]["module"] == "pathlib"

    def test_from_import_multiple(self, parser: PythonParser):
        """Test extracting multiple from imports."""
        source = b'''
from typing import List, Dict, Optional
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 3
        names = [i["name"] for i in imports]
        assert "List" in names
        assert "Dict" in names
        assert "Optional" in names

    def test_from_import_alias(self, parser: PythonParser):
        """Test extracting aliased from import."""
        source = b'''
from typing import List as L
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "L"
        assert imports[0]["metadata"]["alias"] == "L"
        assert imports[0]["metadata"]["original_name"] == "List"

    def test_wildcard_import(self, parser: PythonParser):
        """Test extracting wildcard import."""
        source = b'''
from module import *
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "*"
        assert imports[0]["metadata"]["import_type"] == "wildcard"


class TestCallExtraction:
    """Tests for function call reference extraction."""

    def test_simple_call(self, parser: PythonParser):
        """Test extracting simple function call."""
        source = b'''
def caller():
    callee()
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1
        call = next(c for c in calls if c["target"] == "callee")
        assert call["source"] == "caller"

    def test_method_call(self, parser: PythonParser):
        """Test extracting method call."""
        source = b'''
def process():
    obj.method()
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1
        call = next(c for c in calls if "method" in c["target"])
        assert call["source"] == "process"

    def test_calls_in_class(self, parser: PythonParser):
        """Test extracting calls within class methods."""
        source = b'''
class MyClass:
    def method_a(self):
        self.method_b()
        external_func()

    def method_b(self):
        pass
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        # Should have calls from method_a
        method_a_calls = [c for c in calls if c["source"] == "MyClass.method_a"]
        assert len(method_a_calls) >= 2

    def test_module_level_call(self, parser: PythonParser):
        """Test extracting module-level calls."""
        source = b'''
result = some_function()
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1
        call = next(c for c in calls if c["target"] == "some_function")
        assert call["source"] == "<module>"


class TestInheritanceExtraction:
    """Tests for inheritance relationship extraction."""

    def test_single_inheritance(self, parser: PythonParser):
        """Test extracting single inheritance."""
        source = b'''
class Child(Parent):
    pass
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        inherits = [r for r in refs if r["type"] == "inherits"]
        assert len(inherits) == 1
        assert inherits[0]["source"] == "Child"
        assert inherits[0]["target"] == "Parent"

    def test_multiple_inheritance(self, parser: PythonParser):
        """Test extracting multiple inheritance."""
        source = b'''
class Child(Parent1, Parent2):
    pass
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        inherits = [r for r in refs if r["type"] == "inherits"]
        assert len(inherits) == 2
        targets = [i["target"] for i in inherits]
        assert "Parent1" in targets
        assert "Parent2" in targets


class TestImportEdgeExtraction:
    """Tests for import relationship extraction."""

    def test_import_edge(self, parser: PythonParser):
        """Test extracting import edges."""
        source = b'''
import os
from pathlib import Path
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        imports = [r for r in refs if r["type"] == "imports"]
        assert len(imports) >= 2

        # Check module import
        os_import = next(i for i in imports if i["target"] == "os")
        assert os_import is not None

        # Check from import
        path_import = next(i for i in imports if "pathlib.Path" in i["target"])
        assert path_import is not None


class TestParseToResult:
    """Tests for the high-level parse_to_result method."""

    def test_parse_to_result(self, parser: PythonParser, tmp_path: Path):
        """Test complete parsing workflow."""
        source = '''
"""Module docstring."""

import os
from pathlib import Path


MY_CONSTANT = 42


class MyClass(BaseClass):
    """Class docstring."""

    def method(self):
        """Method docstring."""
        os.getcwd()
        return Path(".")


def standalone():
    pass
'''
        # Write to temp file
        test_file = tmp_path / "test_module.py"
        test_file.write_text(source)

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)
        assert len(result.errors) == 0

        # Check nodes
        node_names = [n.name for n in result.nodes]
        assert "os" in node_names  # import
        assert "Path" in node_names  # from import
        assert "MY_CONSTANT" in node_names  # variable
        assert "MyClass" in node_names  # class
        assert "method" in node_names  # method
        assert "standalone" in node_names  # function

        # Check edges
        edge_types = [e.edge_type for e in result.edges]
        assert "imports" in edge_types
        assert "inherits" in edge_types
        assert "calls" in edge_types

    def test_parse_to_result_with_content(self, parser: PythonParser):
        """Test parsing with content string instead of file."""
        source = '''
def example():
    pass
'''
        result = parser.parse_to_result("virtual.py", content=source)

        assert result.file_path == "virtual.py"
        assert len(result.nodes) == 1
        assert result.nodes[0].name == "example"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, parser: PythonParser):
        """Test parsing empty file."""
        source = b""
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        refs = parser.extract_references(tree, source)

        assert symbols == []
        assert refs == []

    def test_syntax_error(self, parser: PythonParser):
        """Test parsing file with syntax errors."""
        source = b'''
def broken(
    # Missing closing paren
'''
        tree = parser.parse(source)
        # Should still be able to extract what's possible
        assert tree.root_node.has_error

    def test_nested_class(self, parser: PythonParser):
        """Test parsing nested class."""
        source = b'''
class Outer:
    class Inner:
        def inner_method(self):
            pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        methods = [s for s in symbols if s["kind"] == "method"]

        assert len(classes) == 2
        assert any(c["name"] == "Outer" for c in classes)
        assert any(c["name"] == "Inner" for c in classes)
        assert any(m["qualified_name"] == "Outer.Inner.inner_method" for m in methods)

    def test_unicode_identifiers(self, parser: PythonParser):
        """Test parsing unicode identifiers."""
        source = "def 你好(): pass".encode("utf-8")
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 1
        assert funcs[0]["name"] == "你好"

    def test_multiline_docstring(self, parser: PythonParser):
        """Test extracting multiline docstring."""
        source = b'''
def documented():
    """
    This is a multiline
    docstring with
    multiple lines.
    """
    pass
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        funcs = [s for s in symbols if s["kind"] == "function"]
        assert len(funcs) == 1
        docstring = funcs[0]["docstring"]
        assert "multiline" in docstring
        assert "multiple lines" in docstring
