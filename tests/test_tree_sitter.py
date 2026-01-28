"""Tests to verify tree-sitter can parse Python code."""

import pytest


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-python are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_python
        return True
    except ImportError:
        return False


def _get_python_parser():
    """Helper to create a Python parser with proper Language wrapping."""
    from tree_sitter import Language, Parser

    try:
        import tree_sitter_python as tspython

        # The language() function returns a PyCapsule that must be wrapped
        language = Language(tspython.language())
    except ImportError:
        pytest.skip("tree-sitter-python not installed")

    return Parser(language)


@pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-python not installed"
)
def test_tree_sitter_python_parsing():
    """Verify tree-sitter can load Python grammar and parse code."""
    parser = _get_python_parser()

    # Parse a simple Python file
    source_code = b'''
def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

class Greeter:
    def __init__(self, greeting: str = "Hello"):
        self.greeting = greeting

    def greet(self, name: str) -> str:
        return f"{self.greeting}, {name}!"
'''

    tree = parser.parse(source_code)

    # Verify we got a valid tree
    assert tree is not None
    assert tree.root_node is not None
    assert tree.root_node.type == "module"

    # Verify we can find function definitions
    root = tree.root_node
    assert root.child_count > 0

    # Find function_definition nodes
    function_defs = [
        child for child in root.children if child.type == "function_definition"
    ]
    assert len(function_defs) == 1  # 'hello' function

    # Find class_definition nodes
    class_defs = [child for child in root.children if child.type == "class_definition"]
    assert len(class_defs) == 1  # 'Greeter' class

    # Verify no parse errors
    assert not tree.root_node.has_error


@pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-python not installed"
)
def test_tree_sitter_extracts_function_name():
    """Verify we can extract function names from the AST."""
    parser = _get_python_parser()
    source_code = b"def my_function():\n    pass"

    tree = parser.parse(source_code)
    root = tree.root_node

    # Find the function definition
    func_def = next(
        (child for child in root.children if child.type == "function_definition"), None
    )
    assert func_def is not None

    # Find the name node within the function definition
    name_node = next(
        (child for child in func_def.children if child.type == "identifier"), None
    )
    assert name_node is not None

    # Extract the name text
    name_text = source_code[name_node.start_byte : name_node.end_byte].decode("utf-8")
    assert name_text == "my_function"


@pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-python not installed"
)
def test_tree_sitter_handles_syntax_errors():
    """Verify tree-sitter handles syntax errors gracefully."""
    parser = _get_python_parser()

    # Invalid Python syntax
    source_code = b"def broken_function(\n    # missing closing paren and colon"

    tree = parser.parse(source_code)

    # Tree should still be created, but should have errors
    assert tree is not None
    assert tree.root_node is not None
    assert tree.root_node.has_error


def test_schema_imports():
    """Verify schema models can be imported."""
    from code_intel.graph.schema import (
        CodeGraph,
        EdgeKind,
        GraphEdge,
        GraphNode,
        Location,
        NodeKind,
    )

    # Create a simple location
    loc = Location(
        file_path="test.py", start_line=1, start_column=0, end_line=1, end_column=10
    )
    assert loc.file_path == "test.py"

    # Create a node
    node = GraphNode(
        id="test:func:1", name="my_func", kind=NodeKind.FUNCTION, location=loc
    )
    assert node.name == "my_func"
    assert node.kind == NodeKind.FUNCTION

    # Create a graph
    graph = CodeGraph()
    graph.add_node(node)
    assert len(graph.nodes) == 1


def test_client_imports():
    """Verify client can be imported."""
    from code_intel.client import CodeIntelClient

    client = CodeIntelClient()
    assert client is not None


def test_top_level_exports():
    """Verify all expected exports are available from package root."""
    from code_intel import (
        BaseParser,
        CodeGraph,
        CodeIntelClient,
        EdgeKind,
        GraphEdge,
        GraphNode,
        GraphStorage,
        Location,
        NodeKind,
        __version__,
    )

    assert __version__ == "0.1.0"
    # Verify GraphStorage can be instantiated
    storage = GraphStorage()
    assert storage is not None
