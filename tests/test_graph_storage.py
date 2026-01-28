"""Tests for the SQLite graph storage layer."""

import tempfile
from pathlib import Path

import pytest

from code_intel.graph.schema import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)
from code_intel.graph.storage import GraphStorage, SCHEMA_VERSION


@pytest.fixture
def storage() -> GraphStorage:
    """Create an in-memory storage instance for testing."""
    return GraphStorage()


@pytest.fixture
def sample_location() -> Location:
    """Create a sample location for testing."""
    return Location(
        file_path="src/main.py",
        start_line=10,
        start_column=0,
        end_line=15,
        end_column=20,
    )


@pytest.fixture
def sample_node(sample_location: Location) -> GraphNode:
    """Create a sample node for testing."""
    return GraphNode(
        id="test:my_function:10",
        name="my_function",
        kind=NodeKind.FUNCTION,
        location=sample_location,
        qualified_name="main.my_function",
        signature="(x: int, y: int) -> int",
        docstring="Add two numbers together.",
        metadata={"is_async": False},
    )


@pytest.fixture
def sample_nodes(sample_location: Location) -> list[GraphNode]:
    """Create multiple sample nodes for testing."""
    return [
        GraphNode(
            id="test:MyClass:1",
            name="MyClass",
            kind=NodeKind.CLASS,
            location=Location(
                file_path="src/models.py",
                start_line=1,
                start_column=0,
                end_line=20,
                end_column=0,
            ),
            qualified_name="models.MyClass",
        ),
        GraphNode(
            id="test:MyClass.method:5",
            name="method",
            kind=NodeKind.METHOD,
            location=Location(
                file_path="src/models.py",
                start_line=5,
                start_column=4,
                end_line=10,
                end_column=0,
            ),
            qualified_name="models.MyClass.method",
        ),
        GraphNode(
            id="test:helper:25",
            name="helper",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="src/utils.py",
                start_line=25,
                start_column=0,
                end_line=30,
                end_column=0,
            ),
            qualified_name="utils.helper",
        ),
    ]


class TestGraphStorageInit:
    """Tests for GraphStorage initialisation."""

    def test_in_memory_storage(self) -> None:
        """Test creating an in-memory storage instance."""
        storage = GraphStorage()
        assert storage._db_path == ":memory:"

    def test_file_based_storage(self, tmp_path: Path) -> None:
        """Test creating a file-based storage instance."""
        db_path = tmp_path / "test.db"
        storage = GraphStorage(db_path)
        assert storage._db_path == str(db_path.resolve())
        assert db_path.exists()

    def test_schema_version_is_set(self, storage: GraphStorage) -> None:
        """Test that schema version is properly recorded."""
        with storage._get_connection() as conn:
            cursor = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            assert row["version"] == SCHEMA_VERSION


class TestNodeOperations:
    """Tests for node CRUD operations."""

    def test_create_and_get_node(
        self, storage: GraphStorage, sample_node: GraphNode
    ) -> None:
        """Test creating and retrieving a node."""
        storage.create_node(sample_node, repo_path="/project")

        retrieved = storage.get_node(sample_node.id)
        assert retrieved is not None
        assert retrieved.id == sample_node.id
        assert retrieved.name == sample_node.name
        assert retrieved.kind == sample_node.kind
        assert retrieved.location == sample_node.location
        assert retrieved.qualified_name == sample_node.qualified_name
        assert retrieved.signature == sample_node.signature
        assert retrieved.docstring == sample_node.docstring
        assert retrieved.metadata == sample_node.metadata

    def test_get_nonexistent_node(self, storage: GraphStorage) -> None:
        """Test retrieving a node that doesn't exist."""
        result = storage.get_node("nonexistent")
        assert result is None

    def test_update_existing_node(
        self, storage: GraphStorage, sample_node: GraphNode
    ) -> None:
        """Test that creating a node with the same ID updates it."""
        storage.create_node(sample_node, repo_path="/project")

        # Update the node
        updated_node = GraphNode(
            id=sample_node.id,
            name="updated_function",
            kind=NodeKind.FUNCTION,
            location=sample_node.location,
            signature="(a: str) -> str",
        )
        storage.create_node(updated_node, repo_path="/project")

        retrieved = storage.get_node(sample_node.id)
        assert retrieved is not None
        assert retrieved.name == "updated_function"
        assert retrieved.signature == "(a: str) -> str"

    def test_get_nodes_by_name(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test finding nodes by name."""
        for node in sample_nodes:
            storage.create_node(node, repo_path="/project")

        results = storage.get_nodes_by_name("method")
        assert len(results) == 1
        assert results[0].name == "method"

    def test_get_nodes_by_name_with_type_filter(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test finding nodes by name with type filter."""
        for node in sample_nodes:
            storage.create_node(node, repo_path="/project")

        # Should find helper function
        results = storage.get_nodes_by_name(
            "helper", node_type=NodeKind.FUNCTION
        )
        assert len(results) == 1

        # Should not find helper as a class
        results = storage.get_nodes_by_name("helper", node_type=NodeKind.CLASS)
        assert len(results) == 0

    def test_get_nodes_by_file(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test getting all nodes in a file."""
        for node in sample_nodes:
            storage.create_node(node, repo_path="/project")

        results = storage.get_nodes_by_file("src/models.py", repo_path="/project")
        assert len(results) == 2
        assert all(n.location.file_path == "src/models.py" for n in results)

    def test_get_all_nodes(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test getting all nodes."""
        for node in sample_nodes:
            storage.create_node(node, repo_path="/project")

        results = storage.get_all_nodes()
        assert len(results) == 3

    def test_get_all_nodes_filtered_by_repo(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test getting nodes filtered by repository."""
        # Add nodes to different repos
        storage.create_node(sample_nodes[0], repo_path="/project1")
        storage.create_node(sample_nodes[1], repo_path="/project2")

        results = storage.get_all_nodes(repo_path="/project1")
        assert len(results) == 1
        assert results[0].id == sample_nodes[0].id


class TestEdgeOperations:
    """Tests for edge CRUD operations."""

    def test_create_and_get_edge(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test creating and retrieving an edge."""
        # Create nodes first
        for node in sample_nodes[:2]:
            storage.create_node(node, repo_path="/project")

        edge = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CONTAINS,
        )
        edge_id = storage.create_edge(edge)
        assert edge_id > 0

        # Retrieve via get_edges_from
        edges = storage.get_edges_from(sample_nodes[0].id)
        assert len(edges) == 1
        assert edges[0].source_id == sample_nodes[0].id
        assert edges[0].target_id == sample_nodes[1].id
        assert edges[0].kind == EdgeKind.CONTAINS

    def test_edge_with_location(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test creating an edge with location metadata."""
        for node in sample_nodes[:2]:
            storage.create_node(node, repo_path="/project")

        location = Location(
            file_path="src/main.py",
            start_line=42,
            start_column=8,
            end_line=42,
            end_column=20,
        )
        edge = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CALLS,
            location=location,
            metadata={"call_type": "direct"},
        )
        storage.create_edge(edge)

        edges = storage.get_edges_from(sample_nodes[0].id)
        assert len(edges) == 1
        assert edges[0].location is not None
        assert edges[0].location.file_path == "src/main.py"
        assert edges[0].location.start_line == 42
        assert edges[0].metadata == {"call_type": "direct"}

    def test_get_edges_to(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test getting edges pointing to a node."""
        for node in sample_nodes:
            storage.create_node(node, repo_path="/project")

        # Create edges: node[0] -> node[1], node[2] -> node[1]
        edge1 = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CALLS,
        )
        edge2 = GraphEdge(
            source_id=sample_nodes[2].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CALLS,
        )
        storage.create_edge(edge1)
        storage.create_edge(edge2)

        edges = storage.get_edges_to(sample_nodes[1].id)
        assert len(edges) == 2

    def test_get_edges_with_type_filter(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test filtering edges by type."""
        for node in sample_nodes[:2]:
            storage.create_node(node, repo_path="/project")

        # Create different edge types
        edge1 = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CONTAINS,
        )
        edge2 = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CALLS,
        )
        storage.create_edge(edge1)
        storage.create_edge(edge2)

        # Filter by CONTAINS
        contains_edges = storage.get_edges_from(
            sample_nodes[0].id, edge_type=EdgeKind.CONTAINS
        )
        assert len(contains_edges) == 1
        assert contains_edges[0].kind == EdgeKind.CONTAINS

        # Filter by CALLS
        calls_edges = storage.get_edges_from(
            sample_nodes[0].id, edge_type=EdgeKind.CALLS
        )
        assert len(calls_edges) == 1
        assert calls_edges[0].kind == EdgeKind.CALLS


class TestClearOperations:
    """Tests for clearing data."""

    def test_clear_repo(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test clearing all data for a repository."""
        # Add nodes to two repos
        storage.create_node(sample_nodes[0], repo_path="/project1")
        storage.create_node(sample_nodes[1], repo_path="/project1")
        storage.create_node(sample_nodes[2], repo_path="/project2")

        # Add edge in project1
        edge = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CONTAINS,
        )
        storage.create_edge(edge)

        # Clear project1
        deleted = storage.clear_repo("/project1")
        assert deleted == 2

        # Verify project1 is cleared
        assert len(storage.get_all_nodes(repo_path="/project1")) == 0

        # Verify project2 is untouched
        assert len(storage.get_all_nodes(repo_path="/project2")) == 1

    def test_clear_file(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test clearing data for a specific file."""
        for node in sample_nodes:
            storage.create_node(node, repo_path="/project")

        # Clear models.py
        deleted = storage.clear_file("src/models.py", repo_path="/project")
        assert deleted == 2

        # Verify models.py nodes are gone
        assert len(storage.get_nodes_by_file("src/models.py", "/project")) == 0

        # Verify utils.py is untouched
        assert len(storage.get_nodes_by_file("src/utils.py", "/project")) == 1

    def test_cascade_delete_edges(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test that edges are cascade deleted when nodes are deleted."""
        for node in sample_nodes[:2]:
            storage.create_node(node, repo_path="/project")

        edge = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CALLS,
        )
        storage.create_edge(edge)

        # Verify edge exists
        assert len(storage.get_all_edges()) == 1

        # Clear repo
        storage.clear_repo("/project")

        # Verify edges are also deleted
        assert len(storage.get_all_edges()) == 0


class TestCodeGraphConversion:
    """Tests for CodeGraph import/export."""

    def test_to_code_graph(
        self, storage: GraphStorage, sample_nodes: list[GraphNode]
    ) -> None:
        """Test exporting to CodeGraph."""
        for node in sample_nodes:
            storage.create_node(node, repo_path="/project")

        edge = GraphEdge(
            source_id=sample_nodes[0].id,
            target_id=sample_nodes[1].id,
            kind=EdgeKind.CONTAINS,
        )
        storage.create_edge(edge)

        graph = storage.to_code_graph()
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 1

    def test_from_code_graph(self, storage: GraphStorage) -> None:
        """Test importing from CodeGraph."""
        from code_intel.graph.schema import CodeGraph

        nodes = [
            GraphNode(
                id="import:func:1",
                name="func",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="test.py",
                    start_line=1,
                    start_column=0,
                    end_line=5,
                    end_column=0,
                ),
            )
        ]
        edges = [
            GraphEdge(
                source_id="import:func:1",
                target_id="import:func:1",  # Self-reference for simplicity
                kind=EdgeKind.REFERENCES,
            )
        ]
        graph = CodeGraph(nodes=nodes, edges=edges)

        storage.from_code_graph(graph, repo_path="/imported")

        assert len(storage.get_all_nodes()) == 1
        assert len(storage.get_all_edges()) == 1


class TestFilePersistence:
    """Tests for file-based persistence."""

    def test_data_persists_across_instances(self, tmp_path: Path) -> None:
        """Test that data persists when using file-based storage."""
        db_path = tmp_path / "persist.db"

        # Create storage and add data
        storage1 = GraphStorage(db_path)
        node = GraphNode(
            id="persist:test:1",
            name="test",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="test.py",
                start_line=1,
                start_column=0,
                end_line=5,
                end_column=0,
            ),
        )
        storage1.create_node(node, repo_path="/project")

        # Create new storage instance and verify data
        storage2 = GraphStorage(db_path)
        retrieved = storage2.get_node("persist:test:1")
        assert retrieved is not None
        assert retrieved.name == "test"
