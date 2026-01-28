"""Tests for graph query methods in GraphStorage.

These tests focus on complex query scenarios beyond the basic CRUD
tests in test_graph_storage.py.
"""

import pytest

from code_intel.graph.schema import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)
from code_intel.graph.storage import GraphStorage


class TestComplexCallGraphQueries:
    """Tests for call graph queries with complex relationships."""

    @pytest.fixture
    def call_graph_storage(self) -> GraphStorage:
        """Create a storage with a complex call graph.

        Structure:
        - main() calls process() and validate()
        - process() calls transform() and helper()
        - validate() calls helper()
        - helper() calls nothing
        - transform() calls nothing
        """
        storage = GraphStorage()
        repo = "/project"

        nodes = [
            GraphNode(
                id="func:main:1",
                name="main",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="app.py",
                    start_line=1,
                    start_column=0,
                    end_line=10,
                    end_column=0,
                ),
                qualified_name="app.main",
            ),
            GraphNode(
                id="func:process:15",
                name="process",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="app.py",
                    start_line=15,
                    start_column=0,
                    end_line=25,
                    end_column=0,
                ),
                qualified_name="app.process",
            ),
            GraphNode(
                id="func:validate:30",
                name="validate",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="app.py",
                    start_line=30,
                    start_column=0,
                    end_line=40,
                    end_column=0,
                ),
                qualified_name="app.validate",
            ),
            GraphNode(
                id="func:helper:45",
                name="helper",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="utils.py",
                    start_line=45,
                    start_column=0,
                    end_line=55,
                    end_column=0,
                ),
                qualified_name="utils.helper",
            ),
            GraphNode(
                id="func:transform:60",
                name="transform",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="utils.py",
                    start_line=60,
                    start_column=0,
                    end_line=70,
                    end_column=0,
                ),
                qualified_name="utils.transform",
            ),
        ]

        for node in nodes:
            storage.create_node(node, repo)

        edges = [
            # main calls process and validate
            GraphEdge(
                source_id="func:main:1",
                target_id="func:process:15",
                kind=EdgeKind.CALLS,
            ),
            GraphEdge(
                source_id="func:main:1",
                target_id="func:validate:30",
                kind=EdgeKind.CALLS,
            ),
            # process calls transform and helper
            GraphEdge(
                source_id="func:process:15",
                target_id="func:transform:60",
                kind=EdgeKind.CALLS,
            ),
            GraphEdge(
                source_id="func:process:15",
                target_id="func:helper:45",
                kind=EdgeKind.CALLS,
            ),
            # validate calls helper
            GraphEdge(
                source_id="func:validate:30",
                target_id="func:helper:45",
                kind=EdgeKind.CALLS,
            ),
        ]

        for edge in edges:
            storage.create_edge(edge)

        return storage

    def test_find_all_callers_of_leaf_function(
        self, call_graph_storage: GraphStorage
    ) -> None:
        """Test finding all callers of a leaf function (helper)."""
        callers = call_graph_storage.find_callers("helper", "/project")

        assert len(callers) == 2
        caller_names = {c.name for c in callers}
        assert caller_names == {"process", "validate"}

    def test_find_callers_of_root_function(
        self, call_graph_storage: GraphStorage
    ) -> None:
        """Test finding callers of root function (main) - should be empty."""
        callers = call_graph_storage.find_callers("main", "/project")
        assert len(callers) == 0

    def test_find_all_callees_of_entry_function(
        self, call_graph_storage: GraphStorage
    ) -> None:
        """Test finding all direct callees of entry function."""
        callees = call_graph_storage.find_callees("main", "/project")

        assert len(callees) == 2
        callee_names = {c.name for c in callees}
        assert callee_names == {"process", "validate"}

    def test_find_callees_of_middle_function(
        self, call_graph_storage: GraphStorage
    ) -> None:
        """Test finding callees of a middle function."""
        callees = call_graph_storage.find_callees("process", "/project")

        assert len(callees) == 2
        callee_names = {c.name for c in callees}
        assert callee_names == {"transform", "helper"}

    def test_find_callees_of_leaf_function(
        self, call_graph_storage: GraphStorage
    ) -> None:
        """Test finding callees of leaf function - should be empty."""
        callees = call_graph_storage.find_callees("helper", "/project")
        assert len(callees) == 0


class TestReferenceQueries:
    """Tests for reference queries with multiple edge types."""

    @pytest.fixture
    def reference_graph_storage(self) -> GraphStorage:
        """Create a storage with various reference types.

        Structure:
        - UserService class
          - imports UserModel
          - calls validate_user()
          - instantiates Logger
          - inherits BaseService
        """
        storage = GraphStorage()
        repo = "/project"

        nodes = [
            GraphNode(
                id="class:UserService:1",
                name="UserService",
                kind=NodeKind.CLASS,
                location=Location(
                    file_path="services/user.py",
                    start_line=1,
                    start_column=0,
                    end_line=50,
                    end_column=0,
                ),
                qualified_name="services.user.UserService",
            ),
            GraphNode(
                id="class:UserModel:1",
                name="UserModel",
                kind=NodeKind.CLASS,
                location=Location(
                    file_path="models/user.py",
                    start_line=1,
                    start_column=0,
                    end_line=30,
                    end_column=0,
                ),
                qualified_name="models.user.UserModel",
            ),
            GraphNode(
                id="func:validate_user:1",
                name="validate_user",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="validators.py",
                    start_line=1,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
                qualified_name="validators.validate_user",
            ),
            GraphNode(
                id="class:Logger:1",
                name="Logger",
                kind=NodeKind.CLASS,
                location=Location(
                    file_path="logging.py",
                    start_line=1,
                    start_column=0,
                    end_line=40,
                    end_column=0,
                ),
                qualified_name="logging.Logger",
            ),
            GraphNode(
                id="class:BaseService:1",
                name="BaseService",
                kind=NodeKind.CLASS,
                location=Location(
                    file_path="services/base.py",
                    start_line=1,
                    start_column=0,
                    end_line=25,
                    end_column=0,
                ),
                qualified_name="services.base.BaseService",
            ),
        ]

        for node in nodes:
            storage.create_node(node, repo)

        edges = [
            # UserService imports UserModel
            GraphEdge(
                source_id="class:UserService:1",
                target_id="class:UserModel:1",
                kind=EdgeKind.IMPORTS,
            ),
            # UserService calls validate_user
            GraphEdge(
                source_id="class:UserService:1",
                target_id="func:validate_user:1",
                kind=EdgeKind.CALLS,
            ),
            # UserService instantiates Logger
            GraphEdge(
                source_id="class:UserService:1",
                target_id="class:Logger:1",
                kind=EdgeKind.INSTANTIATES,
            ),
            # UserService inherits BaseService
            GraphEdge(
                source_id="class:UserService:1",
                target_id="class:BaseService:1",
                kind=EdgeKind.INHERITS,
            ),
        ]

        for edge in edges:
            storage.create_edge(edge)

        return storage

    def test_find_references_includes_imports(
        self, reference_graph_storage: GraphStorage
    ) -> None:
        """Test that find_references includes import edges."""
        refs = reference_graph_storage.find_references("UserModel", "/project")

        assert len(refs) == 1
        assert refs[0].name == "UserService"

    def test_find_references_includes_calls(
        self, reference_graph_storage: GraphStorage
    ) -> None:
        """Test that find_references includes call edges."""
        refs = reference_graph_storage.find_references("validate_user", "/project")

        assert len(refs) == 1
        assert refs[0].name == "UserService"

    def test_find_references_includes_instantiates(
        self, reference_graph_storage: GraphStorage
    ) -> None:
        """Test that find_references includes instantiation edges."""
        refs = reference_graph_storage.find_references("Logger", "/project")

        assert len(refs) == 1
        assert refs[0].name == "UserService"

    def test_find_references_includes_inherits(
        self, reference_graph_storage: GraphStorage
    ) -> None:
        """Test that find_references includes inheritance edges."""
        refs = reference_graph_storage.find_references("BaseService", "/project")

        assert len(refs) == 1
        assert refs[0].name == "UserService"

    def test_find_callers_only_returns_calls(
        self, reference_graph_storage: GraphStorage
    ) -> None:
        """Test that find_callers only returns CALLS edges."""
        # UserModel is imported, not called
        callers = reference_graph_storage.find_callers("UserModel", "/project")
        assert len(callers) == 0

        # validate_user is called
        callers = reference_graph_storage.find_callers("validate_user", "/project")
        assert len(callers) == 1


class TestSymbolInfoQueries:
    """Tests for get_symbol_info with disambiguation."""

    @pytest.fixture
    def ambiguous_symbols_storage(self) -> GraphStorage:
        """Create a storage with duplicate symbol names."""
        storage = GraphStorage()
        repo = "/project"

        nodes = [
            # Two classes named 'Config' in different modules
            GraphNode(
                id="class:config1:1",
                name="Config",
                kind=NodeKind.CLASS,
                location=Location(
                    file_path="app/config.py",
                    start_line=1,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
                qualified_name="app.config.Config",
                docstring="Application configuration.",
            ),
            GraphNode(
                id="class:config2:1",
                name="Config",
                kind=NodeKind.CLASS,
                location=Location(
                    file_path="db/config.py",
                    start_line=1,
                    start_column=0,
                    end_line=15,
                    end_column=0,
                ),
                qualified_name="db.config.Config",
                docstring="Database configuration.",
            ),
            # A function also named 'config'
            GraphNode(
                id="func:config:1",
                name="config",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="utils.py",
                    start_line=1,
                    start_column=0,
                    end_line=5,
                    end_column=0,
                ),
                qualified_name="utils.config",
                signature="() -> dict",
            ),
        ]

        for node in nodes:
            storage.create_node(node, repo)

        return storage

    def test_get_symbol_info_returns_first_match(
        self, ambiguous_symbols_storage: GraphStorage
    ) -> None:
        """Test that get_symbol_info returns a match when ambiguous."""
        info = ambiguous_symbols_storage.get_symbol_info("Config", "/project")

        assert info is not None
        assert info.name == "Config"
        # Should return one of the Configs (order may vary)

    def test_get_symbol_info_disambiguate_by_qualified_name(
        self, ambiguous_symbols_storage: GraphStorage
    ) -> None:
        """Test disambiguation using qualified_name."""
        info = ambiguous_symbols_storage.get_symbol_info(
            "Config", "/project", qualified_name="db.config.Config"
        )

        assert info is not None
        assert info.qualified_name == "db.config.Config"
        assert info.docstring == "Database configuration."

    def test_get_symbol_info_disambiguate_by_node_type(
        self, ambiguous_symbols_storage: GraphStorage
    ) -> None:
        """Test disambiguation using node_type."""
        info = ambiguous_symbols_storage.get_symbol_info(
            "config", "/project", node_type=NodeKind.FUNCTION
        )

        assert info is not None
        assert info.kind == NodeKind.FUNCTION
        assert info.signature == "() -> dict"

    def test_get_symbol_info_no_match(
        self, ambiguous_symbols_storage: GraphStorage
    ) -> None:
        """Test when no symbol matches criteria."""
        info = ambiguous_symbols_storage.get_symbol_info(
            "Config", "/project", node_type=NodeKind.FUNCTION
        )
        assert info is None


class TestEdgeCaseQueries:
    """Tests for edge cases in graph queries."""

    def test_empty_storage_queries(self) -> None:
        """Test queries on empty storage."""
        storage = GraphStorage()
        repo = "/project"

        assert storage.find_callers("func", repo) == []
        assert storage.find_callees("func", repo) == []
        assert storage.find_references("symbol", repo) == []
        assert storage.get_symbol_info("symbol", repo) is None

    def test_queries_with_wrong_repo(self) -> None:
        """Test that queries are scoped to repo_path."""
        storage = GraphStorage()

        node = GraphNode(
            id="func:test:1",
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
        storage.create_node(node, "/repo1")

        # Query with different repo
        assert storage.get_symbol_info("test", "/repo2") is None

    def test_self_referential_edges(self) -> None:
        """Test handling of self-referential edges (recursion)."""
        storage = GraphStorage()
        repo = "/project"

        node = GraphNode(
            id="func:recursive:1",
            name="recursive",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="test.py",
                start_line=1,
                start_column=0,
                end_line=10,
                end_column=0,
            ),
        )
        storage.create_node(node, repo)

        # Self-referential call (recursion)
        edge = GraphEdge(
            source_id="func:recursive:1",
            target_id="func:recursive:1",
            kind=EdgeKind.CALLS,
        )
        storage.create_edge(edge)

        # Should find itself as both caller and callee
        callers = storage.find_callers("recursive", repo)
        assert len(callers) == 1
        assert callers[0].name == "recursive"

        callees = storage.find_callees("recursive", repo)
        assert len(callees) == 1
        assert callees[0].name == "recursive"
