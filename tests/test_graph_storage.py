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


class TestQueryMethods:
    """Tests for graph query methods."""

    @pytest.fixture
    def query_graph(self, storage: GraphStorage) -> GraphStorage:
        """Create a graph with call relationships for testing queries."""
        # Create nodes: module -> class -> methods, plus helper functions
        nodes = [
            GraphNode(
                id="mod:main:1",
                name="main",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="src/main.py",
                    start_line=1,
                    start_column=0,
                    end_line=100,
                    end_column=0,
                ),
                qualified_name="main",
            ),
            GraphNode(
                id="func:process_data:10",
                name="process_data",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="src/main.py",
                    start_line=10,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
                qualified_name="main.process_data",
                signature="(data: list) -> dict",
            ),
            GraphNode(
                id="func:validate:25",
                name="validate",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="src/main.py",
                    start_line=25,
                    start_column=0,
                    end_line=35,
                    end_column=0,
                ),
                qualified_name="main.validate",
                signature="(item: Any) -> bool",
            ),
            GraphNode(
                id="func:helper:40",
                name="helper",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="src/utils.py",
                    start_line=40,
                    start_column=0,
                    end_line=50,
                    end_column=0,
                ),
                qualified_name="utils.helper",
            ),
            GraphNode(
                id="func:transform:55",
                name="transform",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="src/utils.py",
                    start_line=55,
                    start_column=0,
                    end_line=65,
                    end_column=0,
                ),
                qualified_name="utils.transform",
            ),
            GraphNode(
                id="class:DataProcessor:70",
                name="DataProcessor",
                kind=NodeKind.CLASS,
                location=Location(
                    file_path="src/processor.py",
                    start_line=70,
                    start_column=0,
                    end_line=120,
                    end_column=0,
                ),
                qualified_name="processor.DataProcessor",
            ),
        ]

        for node in nodes:
            storage.create_node(node, repo_path="/project")

        # Create edges for call relationships:
        # process_data calls validate, helper, transform
        # validate calls helper
        # DataProcessor (referenced, not called)
        edges = [
            GraphEdge(
                source_id="func:process_data:10",
                target_id="func:validate:25",
                kind=EdgeKind.CALLS,
            ),
            GraphEdge(
                source_id="func:process_data:10",
                target_id="func:helper:40",
                kind=EdgeKind.CALLS,
            ),
            GraphEdge(
                source_id="func:process_data:10",
                target_id="func:transform:55",
                kind=EdgeKind.CALLS,
            ),
            GraphEdge(
                source_id="func:validate:25",
                target_id="func:helper:40",
                kind=EdgeKind.CALLS,
            ),
            # process_data instantiates DataProcessor
            GraphEdge(
                source_id="func:process_data:10",
                target_id="class:DataProcessor:70",
                kind=EdgeKind.INSTANTIATES,
            ),
            # validate references DataProcessor (type annotation)
            GraphEdge(
                source_id="func:validate:25",
                target_id="class:DataProcessor:70",
                kind=EdgeKind.REFERENCES,
            ),
        ]

        for edge in edges:
            storage.create_edge(edge)

        return storage

    # ========================================================================
    # find_callers tests
    # ========================================================================

    def test_find_callers_basic(self, query_graph: GraphStorage) -> None:
        """Test finding callers of a function."""
        callers = query_graph.find_callers("helper", "/project")

        assert len(callers) == 2
        caller_names = {c.name for c in callers}
        assert caller_names == {"process_data", "validate"}

    def test_find_callers_single(self, query_graph: GraphStorage) -> None:
        """Test finding callers when there's only one."""
        callers = query_graph.find_callers("validate", "/project")

        assert len(callers) == 1
        assert callers[0].name == "process_data"

    def test_find_callers_none(self, query_graph: GraphStorage) -> None:
        """Test finding callers when there are none."""
        callers = query_graph.find_callers("process_data", "/project")
        assert len(callers) == 0

    def test_find_callers_nonexistent_symbol(self, query_graph: GraphStorage) -> None:
        """Test finding callers of a non-existent symbol."""
        callers = query_graph.find_callers("nonexistent", "/project")
        assert len(callers) == 0

    def test_find_callers_wrong_repo(self, query_graph: GraphStorage) -> None:
        """Test that repo_path scopes the search."""
        callers = query_graph.find_callers("helper", "/other_project")
        assert len(callers) == 0

    def test_find_callers_pagination(self, query_graph: GraphStorage) -> None:
        """Test pagination with limit and offset."""
        # helper has 2 callers
        callers_page1 = query_graph.find_callers("helper", "/project", limit=1)
        callers_page2 = query_graph.find_callers("helper", "/project", limit=1, offset=1)

        assert len(callers_page1) == 1
        assert len(callers_page2) == 1
        assert callers_page1[0].name != callers_page2[0].name

    def test_find_callers_offset_only(self, query_graph: GraphStorage) -> None:
        """Test pagination with offset only."""
        # helper has 2 callers, skip the first
        callers = query_graph.find_callers("helper", "/project", offset=1)
        assert len(callers) == 1

    # ========================================================================
    # find_callees tests
    # ========================================================================

    def test_find_callees_multiple(self, query_graph: GraphStorage) -> None:
        """Test finding callees of a function with multiple calls."""
        callees = query_graph.find_callees("process_data", "/project")

        assert len(callees) == 3
        callee_names = {c.name for c in callees}
        assert callee_names == {"validate", "helper", "transform"}

    def test_find_callees_single(self, query_graph: GraphStorage) -> None:
        """Test finding callees when there's only one."""
        callees = query_graph.find_callees("validate", "/project")

        assert len(callees) == 1
        assert callees[0].name == "helper"

    def test_find_callees_none(self, query_graph: GraphStorage) -> None:
        """Test finding callees when function calls nothing."""
        callees = query_graph.find_callees("helper", "/project")
        assert len(callees) == 0

    def test_find_callees_pagination(self, query_graph: GraphStorage) -> None:
        """Test callees pagination."""
        # process_data calls 3 functions
        callees_page1 = query_graph.find_callees("process_data", "/project", limit=2)
        callees_page2 = query_graph.find_callees(
            "process_data", "/project", limit=2, offset=2
        )

        assert len(callees_page1) == 2
        assert len(callees_page2) == 1

    # ========================================================================
    # find_references tests
    # ========================================================================

    def test_find_references_includes_calls(self, query_graph: GraphStorage) -> None:
        """Test that find_references includes call relationships."""
        refs = query_graph.find_references("helper", "/project")

        assert len(refs) == 2
        ref_names = {r.name for r in refs}
        assert ref_names == {"process_data", "validate"}

    def test_find_references_includes_instantiates(
        self, query_graph: GraphStorage
    ) -> None:
        """Test that find_references includes instantiation relationships."""
        refs = query_graph.find_references("DataProcessor", "/project")

        assert len(refs) == 2
        ref_names = {r.name for r in refs}
        # process_data instantiates it, validate references it
        assert ref_names == {"process_data", "validate"}

    def test_find_references_broader_than_callers(
        self, query_graph: GraphStorage
    ) -> None:
        """Test that find_references is broader than find_callers."""
        # DataProcessor is instantiated and referenced, but not "called"
        callers = query_graph.find_callers("DataProcessor", "/project")
        refs = query_graph.find_references("DataProcessor", "/project")

        # Callers only finds CALLS edges
        assert len(callers) == 0
        # References finds INSTANTIATES and REFERENCES edges
        assert len(refs) == 2

    def test_find_references_pagination(self, query_graph: GraphStorage) -> None:
        """Test references pagination."""
        refs_page1 = query_graph.find_references("helper", "/project", limit=1)
        refs_page2 = query_graph.find_references("helper", "/project", limit=1, offset=1)

        assert len(refs_page1) == 1
        assert len(refs_page2) == 1
        assert refs_page1[0].name != refs_page2[0].name

    # ========================================================================
    # get_symbol_info tests
    # ========================================================================

    def test_get_symbol_info_basic(self, query_graph: GraphStorage) -> None:
        """Test getting symbol info by name."""
        info = query_graph.get_symbol_info("process_data", "/project")

        assert info is not None
        assert info.name == "process_data"
        assert info.kind == NodeKind.FUNCTION
        assert info.qualified_name == "main.process_data"
        assert info.signature == "(data: list) -> dict"

    def test_get_symbol_info_not_found(self, query_graph: GraphStorage) -> None:
        """Test get_symbol_info returns None for non-existent symbol."""
        info = query_graph.get_symbol_info("nonexistent", "/project")
        assert info is None

    def test_get_symbol_info_wrong_repo(self, query_graph: GraphStorage) -> None:
        """Test that repo_path scopes the search."""
        info = query_graph.get_symbol_info("process_data", "/other_project")
        assert info is None

    def test_get_symbol_info_with_qualified_name(
        self, query_graph: GraphStorage
    ) -> None:
        """Test disambiguation by qualified name."""
        # Create a second 'helper' in a different module
        storage = query_graph
        second_helper = GraphNode(
            id="func:helper2:100",
            name="helper",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="src/other.py",
                start_line=100,
                start_column=0,
                end_line=110,
                end_column=0,
            ),
            qualified_name="other.helper",
        )
        storage.create_node(second_helper, repo_path="/project")

        # Get by qualified name
        info = storage.get_symbol_info(
            "helper", "/project", qualified_name="utils.helper"
        )

        assert info is not None
        assert info.qualified_name == "utils.helper"

    def test_get_symbol_info_with_node_type(self, query_graph: GraphStorage) -> None:
        """Test disambiguation by node type."""
        info = query_graph.get_symbol_info(
            "DataProcessor", "/project", node_type=NodeKind.CLASS
        )

        assert info is not None
        assert info.kind == NodeKind.CLASS

        # Try with wrong type
        info = query_graph.get_symbol_info(
            "DataProcessor", "/project", node_type=NodeKind.FUNCTION
        )
        assert info is None


class TestImportGraph:
    """Tests for get_import_graph method."""

    @pytest.fixture
    def import_graph(self, storage: GraphStorage) -> GraphStorage:
        """Create a graph with import relationships for testing."""
        # File structure:
        # main.py imports utils.py
        # utils.py imports helpers.py
        # helpers.py imports nothing
        nodes = [
            GraphNode(
                id="mod:main:1",
                name="main",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="src/main.py",
                    start_line=1,
                    start_column=0,
                    end_line=50,
                    end_column=0,
                ),
            ),
            GraphNode(
                id="mod:utils:1",
                name="utils",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="src/utils.py",
                    start_line=1,
                    start_column=0,
                    end_line=30,
                    end_column=0,
                ),
            ),
            GraphNode(
                id="mod:helpers:1",
                name="helpers",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="src/helpers.py",
                    start_line=1,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
            ),
            GraphNode(
                id="mod:unrelated:1",
                name="unrelated",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="src/unrelated.py",
                    start_line=1,
                    start_column=0,
                    end_line=10,
                    end_column=0,
                ),
            ),
        ]

        for node in nodes:
            storage.create_node(node, repo_path="/project")

        # Import edges: main -> utils -> helpers
        edges = [
            GraphEdge(
                source_id="mod:main:1",
                target_id="mod:utils:1",
                kind=EdgeKind.IMPORTS,
            ),
            GraphEdge(
                source_id="mod:utils:1",
                target_id="mod:helpers:1",
                kind=EdgeKind.IMPORTS,
            ),
        ]

        for edge in edges:
            storage.create_edge(edge)

        return storage

    def test_get_import_graph_depth_1(self, import_graph: GraphStorage) -> None:
        """Test getting direct imports only."""
        edges = import_graph.get_import_graph("src/main.py", "/project", depth=1)

        assert len(edges) == 1
        assert edges[0].target_id == "mod:utils:1"

    def test_get_import_graph_depth_2(self, import_graph: GraphStorage) -> None:
        """Test getting transitive imports."""
        edges = import_graph.get_import_graph("src/main.py", "/project", depth=2)

        assert len(edges) == 2
        target_ids = {e.target_id for e in edges}
        assert target_ids == {"mod:utils:1", "mod:helpers:1"}

    def test_get_import_graph_no_imports(self, import_graph: GraphStorage) -> None:
        """Test file with no imports."""
        edges = import_graph.get_import_graph("src/helpers.py", "/project", depth=1)
        assert len(edges) == 0

    def test_get_import_graph_depth_zero(self, import_graph: GraphStorage) -> None:
        """Test depth 0 returns empty list."""
        edges = import_graph.get_import_graph("src/main.py", "/project", depth=0)
        assert len(edges) == 0

    def test_get_import_graph_nonexistent_file(
        self, import_graph: GraphStorage
    ) -> None:
        """Test non-existent file returns empty list."""
        edges = import_graph.get_import_graph("nonexistent.py", "/project", depth=1)
        assert len(edges) == 0

    def test_get_import_graph_handles_cycles(self, storage: GraphStorage) -> None:
        """Test that import cycles don't cause infinite loops."""
        # Create a cycle: a -> b -> c -> a
        nodes = [
            GraphNode(
                id="mod:a:1",
                name="a",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="a.py",
                    start_line=1,
                    start_column=0,
                    end_line=10,
                    end_column=0,
                ),
            ),
            GraphNode(
                id="mod:b:1",
                name="b",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="b.py",
                    start_line=1,
                    start_column=0,
                    end_line=10,
                    end_column=0,
                ),
            ),
            GraphNode(
                id="mod:c:1",
                name="c",
                kind=NodeKind.MODULE,
                location=Location(
                    file_path="c.py",
                    start_line=1,
                    start_column=0,
                    end_line=10,
                    end_column=0,
                ),
            ),
        ]

        for node in nodes:
            storage.create_node(node, repo_path="/project")

        edges = [
            GraphEdge(source_id="mod:a:1", target_id="mod:b:1", kind=EdgeKind.IMPORTS),
            GraphEdge(source_id="mod:b:1", target_id="mod:c:1", kind=EdgeKind.IMPORTS),
            GraphEdge(source_id="mod:c:1", target_id="mod:a:1", kind=EdgeKind.IMPORTS),
        ]

        for edge in edges:
            storage.create_edge(edge)

        # Should complete without infinite loop and return all edges
        result_edges = storage.get_import_graph("a.py", "/project", depth=10)

        # Should have all 3 edges (a->b, b->c, c->a)
        assert len(result_edges) == 3
