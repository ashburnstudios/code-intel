"""Shared pytest fixtures for code-intel tests."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from code_intel.graph.schema import (
    CodeGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)
from code_intel.graph.storage import GraphStorage

if TYPE_CHECKING:
    from code_intel.parser.base import BaseParser


# =============================================================================
# Path fixtures
# =============================================================================


@pytest.fixture
def fixtures_path() -> Path:
    """Return the path to test fixtures directory."""
    return Path(__file__).parent / "test_parser" / "fixtures"


@pytest.fixture
def simple_functions_file(fixtures_path: Path) -> Path:
    """Return path to simple_functions.py fixture."""
    return fixtures_path / "simple_functions.py"


@pytest.fixture
def classes_file(fixtures_path: Path) -> Path:
    """Return path to classes.py fixture."""
    return fixtures_path / "classes.py"


@pytest.fixture
def imports_file(fixtures_path: Path) -> Path:
    """Return path to imports.py fixture."""
    return fixtures_path / "imports.py"


@pytest.fixture
def call_chains_file(fixtures_path: Path) -> Path:
    """Return path to call_chains.py fixture."""
    return fixtures_path / "call_chains.py"


@pytest.fixture
def decorators_file(fixtures_path: Path) -> Path:
    """Return path to decorators.py fixture."""
    return fixtures_path / "decorators.py"


@pytest.fixture
def variables_file(fixtures_path: Path) -> Path:
    """Return path to variables.py fixture."""
    return fixtures_path / "variables.py"


@pytest.fixture
def syntax_errors_file(fixtures_path: Path) -> Path:
    """Return path to syntax_errors.py fixture."""
    return fixtures_path / "syntax_errors.py"


# =============================================================================
# Graph fixtures
# =============================================================================


@pytest.fixture
def in_memory_storage() -> GraphStorage:
    """Create an in-memory storage instance."""
    return GraphStorage()


@pytest.fixture
def sample_location() -> Location:
    """Create a sample location."""
    return Location(
        file_path="src/example.py",
        start_line=10,
        start_column=0,
        end_line=20,
        end_column=0,
    )


@pytest.fixture
def sample_node(sample_location: Location) -> GraphNode:
    """Create a sample GraphNode."""
    return GraphNode(
        id="test:sample_function:10",
        name="sample_function",
        kind=NodeKind.FUNCTION,
        location=sample_location,
        qualified_name="example.sample_function",
        signature="(x: int) -> str",
        docstring="A sample function.",
    )


@pytest.fixture
def sample_nodes() -> list[GraphNode]:
    """Create a list of sample GraphNodes with relationships."""
    return [
        GraphNode(
            id="test:ModuleA:1",
            name="ModuleA",
            kind=NodeKind.MODULE,
            location=Location(
                file_path="src/module_a.py",
                start_line=1,
                start_column=0,
                end_line=50,
                end_column=0,
            ),
            qualified_name="module_a",
        ),
        GraphNode(
            id="test:ClassA:5",
            name="ClassA",
            kind=NodeKind.CLASS,
            location=Location(
                file_path="src/module_a.py",
                start_line=5,
                start_column=0,
                end_line=30,
                end_column=0,
            ),
            qualified_name="module_a.ClassA",
            docstring="A sample class.",
        ),
        GraphNode(
            id="test:ClassA.method:10",
            name="method",
            kind=NodeKind.METHOD,
            location=Location(
                file_path="src/module_a.py",
                start_line=10,
                start_column=4,
                end_line=15,
                end_column=0,
            ),
            qualified_name="module_a.ClassA.method",
            signature="(self, x: int) -> None",
        ),
        GraphNode(
            id="test:helper_func:35",
            name="helper_func",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="src/module_a.py",
                start_line=35,
                start_column=0,
                end_line=40,
                end_column=0,
            ),
            qualified_name="module_a.helper_func",
        ),
        GraphNode(
            id="test:CONSTANT:1",
            name="CONSTANT",
            kind=NodeKind.VARIABLE,
            location=Location(
                file_path="src/module_a.py",
                start_line=1,
                start_column=0,
                end_line=1,
                end_column=15,
            ),
            qualified_name="module_a.CONSTANT",
        ),
    ]


@pytest.fixture
def sample_edges(sample_nodes: list[GraphNode]) -> list[GraphEdge]:
    """Create sample edges between sample_nodes."""
    return [
        # Module contains class
        GraphEdge(
            source_id="test:ModuleA:1",
            target_id="test:ClassA:5",
            kind=EdgeKind.CONTAINS,
        ),
        # Class contains method
        GraphEdge(
            source_id="test:ClassA:5",
            target_id="test:ClassA.method:10",
            kind=EdgeKind.CONTAINS,
        ),
        # Method calls helper_func
        GraphEdge(
            source_id="test:ClassA.method:10",
            target_id="test:helper_func:35",
            kind=EdgeKind.CALLS,
            location=Location(
                file_path="src/module_a.py",
                start_line=12,
                start_column=8,
                end_line=12,
                end_column=20,
            ),
        ),
        # Helper references constant
        GraphEdge(
            source_id="test:helper_func:35",
            target_id="test:CONSTANT:1",
            kind=EdgeKind.REFERENCES,
        ),
    ]


@pytest.fixture
def populated_graph(sample_nodes: list[GraphNode], sample_edges: list[GraphEdge]) -> CodeGraph:
    """Create a CodeGraph populated with sample data."""
    graph = CodeGraph()
    for node in sample_nodes:
        graph.add_node(node)
    for edge in sample_edges:
        graph.add_edge(edge)
    return graph


@pytest.fixture
def populated_storage(
    in_memory_storage: GraphStorage,
    sample_nodes: list[GraphNode],
    sample_edges: list[GraphEdge],
) -> GraphStorage:
    """Create a storage instance populated with sample data."""
    repo_path = "/test/repo"
    for node in sample_nodes:
        in_memory_storage.create_node(node, repo_path)
    for edge in sample_edges:
        in_memory_storage.create_edge(edge)
    return in_memory_storage


# =============================================================================
# Parser fixtures (conditionally loaded)
# =============================================================================


def _check_tree_sitter_available() -> bool:
    """Check if tree-sitter and tree-sitter-python are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_python

        return True
    except ImportError:
        return False


# Marker for tests requiring tree-sitter
requires_tree_sitter = pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-python not installed",
)


@pytest.fixture
def python_parser() -> "BaseParser":
    """Create a Python parser (skips if tree-sitter not available)."""
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_python")

    from code_intel.parser.python import PythonParser

    return PythonParser()
