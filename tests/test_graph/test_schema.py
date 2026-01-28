"""Tests for graph schema models."""

import pytest
from pydantic import ValidationError

from code_intel.graph.schema import (
    CodeGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)


class TestLocation:
    """Tests for Location model."""

    def test_valid_location(self) -> None:
        """Test creating a valid location."""
        loc = Location(
            file_path="src/main.py",
            start_line=10,
            start_column=0,
            end_line=20,
            end_column=15,
        )
        assert loc.file_path == "src/main.py"
        assert loc.start_line == 10
        assert loc.start_column == 0
        assert loc.end_line == 20
        assert loc.end_column == 15

    def test_minimum_valid_values(self) -> None:
        """Test minimum valid values for location."""
        loc = Location(
            file_path="x",
            start_line=1,
            start_column=0,
            end_line=1,
            end_column=0,
        )
        assert loc.start_line == 1
        assert loc.start_column == 0

    def test_invalid_start_line(self) -> None:
        """Test that start_line < 1 is rejected."""
        with pytest.raises(ValidationError):
            Location(
                file_path="test.py",
                start_line=0,  # Invalid - must be >= 1
                start_column=0,
                end_line=1,
                end_column=0,
            )

    def test_invalid_end_line(self) -> None:
        """Test that end_line < 1 is rejected."""
        with pytest.raises(ValidationError):
            Location(
                file_path="test.py",
                start_line=1,
                start_column=0,
                end_line=0,  # Invalid - must be >= 1
                end_column=0,
            )

    def test_invalid_start_column(self) -> None:
        """Test that start_column < 0 is rejected."""
        with pytest.raises(ValidationError):
            Location(
                file_path="test.py",
                start_line=1,
                start_column=-1,  # Invalid - must be >= 0
                end_line=1,
                end_column=0,
            )

    def test_invalid_end_column(self) -> None:
        """Test that end_column < 0 is rejected."""
        with pytest.raises(ValidationError):
            Location(
                file_path="test.py",
                start_line=1,
                start_column=0,
                end_line=1,
                end_column=-1,  # Invalid - must be >= 0
            )

    def test_location_equality(self) -> None:
        """Test location equality comparison."""
        loc1 = Location(
            file_path="test.py",
            start_line=10,
            start_column=5,
            end_line=20,
            end_column=15,
        )
        loc2 = Location(
            file_path="test.py",
            start_line=10,
            start_column=5,
            end_line=20,
            end_column=15,
        )
        assert loc1 == loc2

    def test_location_inequality(self) -> None:
        """Test location inequality comparison."""
        loc1 = Location(
            file_path="test.py",
            start_line=10,
            start_column=5,
            end_line=20,
            end_column=15,
        )
        loc2 = Location(
            file_path="other.py",
            start_line=10,
            start_column=5,
            end_line=20,
            end_column=15,
        )
        assert loc1 != loc2


class TestNodeKind:
    """Tests for NodeKind enum."""

    def test_all_node_kinds_are_strings(self) -> None:
        """Test that all NodeKind values are strings."""
        for kind in NodeKind:
            assert isinstance(kind.value, str)

    def test_expected_node_kinds_exist(self) -> None:
        """Test that expected node kinds exist."""
        expected = [
            "module", "class", "function", "method", "property",
            "variable", "parameter", "constant", "type_alias",
            "interface", "enum", "enum_member", "import", "decorator",
        ]
        for name in expected:
            assert hasattr(NodeKind, name.upper())

    def test_node_kind_from_value(self) -> None:
        """Test creating NodeKind from string value."""
        assert NodeKind("function") == NodeKind.FUNCTION
        assert NodeKind("class") == NodeKind.CLASS


class TestEdgeKind:
    """Tests for EdgeKind enum."""

    def test_all_edge_kinds_are_strings(self) -> None:
        """Test that all EdgeKind values are strings."""
        for kind in EdgeKind:
            assert isinstance(kind.value, str)

    def test_expected_edge_kinds_exist(self) -> None:
        """Test that expected edge kinds exist."""
        expected = [
            "contains", "inherits", "implements", "calls",
            "references", "imports", "instantiates", "returns",
            "parameter_type", "type_of",
        ]
        for name in expected:
            assert hasattr(EdgeKind, name.upper())

    def test_edge_kind_from_value(self) -> None:
        """Test creating EdgeKind from string value."""
        assert EdgeKind("calls") == EdgeKind.CALLS
        assert EdgeKind("imports") == EdgeKind.IMPORTS


class TestGraphNode:
    """Tests for GraphNode model."""

    def test_minimal_node(self, sample_location: Location) -> None:
        """Test creating node with minimal required fields."""
        node = GraphNode(
            id="node:1",
            name="test",
            kind=NodeKind.FUNCTION,
            location=sample_location,
        )
        assert node.id == "node:1"
        assert node.name == "test"
        assert node.kind == NodeKind.FUNCTION
        assert node.qualified_name is None
        assert node.signature is None
        assert node.docstring is None
        assert node.metadata == {}

    def test_full_node(self, sample_location: Location) -> None:
        """Test creating node with all fields."""
        node = GraphNode(
            id="node:full:1",
            name="full_test",
            kind=NodeKind.METHOD,
            location=sample_location,
            qualified_name="MyClass.full_test",
            signature="(self, x: int) -> str",
            docstring="A full test node.",
            metadata={"async": True, "decorators": ["property"]},
        )
        assert node.qualified_name == "MyClass.full_test"
        assert node.signature == "(self, x: int) -> str"
        assert node.docstring == "A full test node."
        assert node.metadata == {"async": True, "decorators": ["property"]}

    def test_node_kind_validation(self, sample_location: Location) -> None:
        """Test that invalid kind is rejected."""
        with pytest.raises(ValidationError):
            GraphNode(
                id="node:1",
                name="test",
                kind="invalid_kind",  # type: ignore
                location=sample_location,
            )

    def test_node_metadata_default(self, sample_location: Location) -> None:
        """Test that metadata defaults to empty dict."""
        node = GraphNode(
            id="node:1",
            name="test",
            kind=NodeKind.VARIABLE,
            location=sample_location,
        )
        assert node.metadata == {}
        # Ensure it's a new dict instance
        node.metadata["key"] = "value"
        assert node.metadata == {"key": "value"}


class TestGraphEdge:
    """Tests for GraphEdge model."""

    def test_minimal_edge(self) -> None:
        """Test creating edge with minimal required fields."""
        edge = GraphEdge(
            source_id="node:1",
            target_id="node:2",
            kind=EdgeKind.CALLS,
        )
        assert edge.source_id == "node:1"
        assert edge.target_id == "node:2"
        assert edge.kind == EdgeKind.CALLS
        assert edge.location is None
        assert edge.metadata == {}

    def test_full_edge(self, sample_location: Location) -> None:
        """Test creating edge with all fields."""
        edge = GraphEdge(
            source_id="node:caller",
            target_id="node:callee",
            kind=EdgeKind.CALLS,
            location=sample_location,
            metadata={"call_type": "method", "line": 42},
        )
        assert edge.location == sample_location
        assert edge.metadata == {"call_type": "method", "line": 42}

    def test_edge_kind_validation(self) -> None:
        """Test that invalid kind is rejected."""
        with pytest.raises(ValidationError):
            GraphEdge(
                source_id="a",
                target_id="b",
                kind="invalid",  # type: ignore
            )


class TestCodeGraph:
    """Tests for CodeGraph model."""

    def test_empty_graph(self) -> None:
        """Test creating an empty graph."""
        graph = CodeGraph()
        assert graph.nodes == []
        assert graph.edges == []

    def test_add_node(self, sample_node: GraphNode) -> None:
        """Test adding a node to the graph."""
        graph = CodeGraph()
        graph.add_node(sample_node)
        assert len(graph.nodes) == 1
        assert graph.nodes[0] == sample_node

    def test_add_multiple_nodes(self, sample_nodes: list[GraphNode]) -> None:
        """Test adding multiple nodes."""
        graph = CodeGraph()
        for node in sample_nodes:
            graph.add_node(node)
        assert len(graph.nodes) == len(sample_nodes)

    def test_add_edge(self, sample_nodes: list[GraphNode]) -> None:
        """Test adding an edge to the graph."""
        graph = CodeGraph()
        for node in sample_nodes[:2]:
            graph.add_node(node)

        edge = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CONTAINS,
        )
        graph.add_edge(edge)

        assert len(graph.edges) == 1
        assert graph.edges[0] == edge

    def test_get_node_found(self, populated_graph: CodeGraph) -> None:
        """Test getting a node that exists."""
        node = populated_graph.get_node("test:ClassA:5")
        assert node is not None
        assert node.name == "ClassA"

    def test_get_node_not_found(self, populated_graph: CodeGraph) -> None:
        """Test getting a node that doesn't exist."""
        node = populated_graph.get_node("nonexistent")
        assert node is None

    def test_get_edges_from(self, populated_graph: CodeGraph) -> None:
        """Test getting edges originating from a node."""
        edges = populated_graph.get_edges_from("test:ClassA:5")
        assert len(edges) == 1
        assert edges[0].kind == EdgeKind.CONTAINS
        assert edges[0].target_id == "test:ClassA.method:10"

    def test_get_edges_from_none(self, populated_graph: CodeGraph) -> None:
        """Test getting edges from a node with no outgoing edges."""
        edges = populated_graph.get_edges_from("test:CONSTANT:1")
        assert edges == []

    def test_get_edges_to(self, populated_graph: CodeGraph) -> None:
        """Test getting edges pointing to a node."""
        edges = populated_graph.get_edges_to("test:ClassA.method:10")
        assert len(edges) == 1
        assert edges[0].kind == EdgeKind.CONTAINS
        assert edges[0].source_id == "test:ClassA:5"

    def test_get_edges_to_none(self, populated_graph: CodeGraph) -> None:
        """Test getting edges to a node with no incoming edges."""
        edges = populated_graph.get_edges_to("test:ModuleA:1")
        assert edges == []

    def test_get_edges_to_multiple(self, sample_nodes: list[GraphNode]) -> None:
        """Test getting multiple edges pointing to a single node."""
        graph = CodeGraph()
        for node in sample_nodes[:3]:
            graph.add_node(node)

        # Both ModuleA and ClassA point to method
        graph.add_edge(GraphEdge(
            source_id="test:ModuleA:1",
            target_id="test:ClassA.method:10",
            kind=EdgeKind.REFERENCES,
        ))
        graph.add_edge(GraphEdge(
            source_id="test:ClassA:5",
            target_id="test:ClassA.method:10",
            kind=EdgeKind.CONTAINS,
        ))

        edges = graph.get_edges_to("test:ClassA.method:10")
        assert len(edges) == 2

    def test_graph_with_initial_data(
        self,
        sample_nodes: list[GraphNode],
        sample_edges: list[GraphEdge],
    ) -> None:
        """Test creating a graph with initial nodes and edges."""
        graph = CodeGraph(nodes=sample_nodes, edges=sample_edges)
        assert len(graph.nodes) == len(sample_nodes)
        assert len(graph.edges) == len(sample_edges)


class TestNodeKindStringEnum:
    """Test that NodeKind is properly a string enum."""

    def test_node_kind_is_string(self) -> None:
        """Test that NodeKind values can be used as strings."""
        assert NodeKind.FUNCTION == "function"
        assert NodeKind.CLASS == "class"
        assert NodeKind.METHOD.value == "method"

    def test_node_kind_in_dict(self) -> None:
        """Test that NodeKind can be used as dict key."""
        d = {NodeKind.FUNCTION: 1, NodeKind.CLASS: 2}
        assert d[NodeKind.FUNCTION] == 1
        assert d["function"] == 1  # String access also works


class TestEdgeKindStringEnum:
    """Test that EdgeKind is properly a string enum."""

    def test_edge_kind_is_string(self) -> None:
        """Test that EdgeKind values can be used as strings."""
        assert EdgeKind.CALLS == "calls"
        assert EdgeKind.IMPORTS == "imports"
        assert EdgeKind.INHERITS.value == "inherits"

    def test_edge_kind_in_dict(self) -> None:
        """Test that EdgeKind can be used as dict key."""
        d = {EdgeKind.CALLS: 1, EdgeKind.IMPORTS: 2}
        assert d[EdgeKind.CALLS] == 1
        assert d["calls"] == 1
