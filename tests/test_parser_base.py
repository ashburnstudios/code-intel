"""Tests for the base parser interface and dataclasses."""

import pytest
from pathlib import Path
from typing import TYPE_CHECKING

from code_intel.parser.base import (
    BaseParser,
    ParsedEdge,
    ParsedNode,
    ParseResult,
)

if TYPE_CHECKING:
    from tree_sitter import Language, Tree


class MockParser(BaseParser):
    """Mock parser for testing the base interface."""

    @property
    def language_name(self) -> str:
        return "mock"

    @property
    def file_extensions(self) -> list[str]:
        return [".mock", ".mk"]

    def _load_language(self) -> "Language":
        """Return a mock language - not actually used in tests."""
        raise NotImplementedError("Mock parser doesn't load real language")

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        """Return mock symbols."""
        return [
            {
                "name": "mock_function",
                "kind": "function",
                "line": 1,
                "end_line": 5,
                "start_column": 0,
                "end_column": 10,
                "signature": "def mock_function(x: int) -> str",
                "docstring": "A mock function.",
            },
            {
                "name": "MockClass",
                "kind": "class",
                "line": 7,
                "end_line": 15,
                "qualified_name": "module.MockClass",
            },
        ]

    def extract_references(self, tree: "Tree", source: bytes) -> list[dict]:
        """Return mock references."""
        return [
            {
                "source": "mock_function",
                "target": "helper",
                "type": "calls",
                "line": 3,
                "column": 4,
            },
            {
                "source": "MockClass",
                "target": "BaseClass",
                "type": "inherits",
            },
        ]


class TestParsedNode:
    """Tests for ParsedNode dataclass."""

    def test_required_fields(self):
        """Test creating a node with required fields only."""
        node = ParsedNode(
            node_type="function",
            name="my_func",
            start_line=1,
            end_line=5,
        )
        assert node.node_type == "function"
        assert node.name == "my_func"
        assert node.start_line == 1
        assert node.end_line == 5
        assert node.signature is None
        assert node.docstring is None

    def test_all_fields(self):
        """Test creating a node with all fields."""
        node = ParsedNode(
            node_type="method",
            name="calculate",
            start_line=10,
            end_line=20,
            signature="def calculate(self, x: int) -> float",
            docstring="Calculate something.",
            start_column=4,
            end_column=8,
            qualified_name="MyClass.calculate",
            metadata={"async": True},
        )
        assert node.node_type == "method"
        assert node.name == "calculate"
        assert node.signature == "def calculate(self, x: int) -> float"
        assert node.docstring == "Calculate something."
        assert node.start_column == 4
        assert node.end_column == 8
        assert node.qualified_name == "MyClass.calculate"
        assert node.metadata == {"async": True}

    def test_default_columns(self):
        """Test that columns default to 0."""
        node = ParsedNode(
            node_type="variable",
            name="x",
            start_line=1,
            end_line=1,
        )
        assert node.start_column == 0
        assert node.end_column == 0

    def test_default_metadata(self):
        """Test that metadata defaults to empty dict."""
        node = ParsedNode(
            node_type="class",
            name="MyClass",
            start_line=1,
            end_line=10,
        )
        assert node.metadata == {}
        # Should be mutable
        node.metadata["key"] = "value"
        assert node.metadata == {"key": "value"}


class TestParsedEdge:
    """Tests for ParsedEdge dataclass."""

    def test_required_fields(self):
        """Test creating an edge with required fields only."""
        edge = ParsedEdge(
            source_name="caller",
            target_name="callee",
            edge_type="calls",
        )
        assert edge.source_name == "caller"
        assert edge.target_name == "callee"
        assert edge.edge_type == "calls"
        assert edge.source_location is None

    def test_all_fields(self):
        """Test creating an edge with all fields."""
        edge = ParsedEdge(
            source_name="ChildClass",
            target_name="ParentClass",
            edge_type="inherits",
            source_location=(5, 10),
            metadata={"multiple": False},
        )
        assert edge.source_name == "ChildClass"
        assert edge.target_name == "ParentClass"
        assert edge.edge_type == "inherits"
        assert edge.source_location == (5, 10)
        assert edge.metadata == {"multiple": False}

    def test_edge_types(self):
        """Test different edge types."""
        edge_types = ["calls", "imports", "inherits", "references"]
        for edge_type in edge_types:
            edge = ParsedEdge(
                source_name="a",
                target_name="b",
                edge_type=edge_type,
            )
            assert edge.edge_type == edge_type


class TestParseResult:
    """Tests for ParseResult dataclass."""

    def test_empty_result(self):
        """Test creating an empty result."""
        result = ParseResult(file_path="test.py")
        assert result.file_path == "test.py"
        assert result.nodes == []
        assert result.edges == []
        assert result.errors == []

    def test_result_with_data(self):
        """Test creating a result with nodes and edges."""
        nodes = [
            ParsedNode(node_type="function", name="f", start_line=1, end_line=5),
        ]
        edges = [
            ParsedEdge(source_name="f", target_name="g", edge_type="calls"),
        ]
        errors = ["Warning: something"]

        result = ParseResult(
            file_path="/path/to/file.py",
            nodes=nodes,
            edges=edges,
            errors=errors,
        )
        assert result.file_path == "/path/to/file.py"
        assert len(result.nodes) == 1
        assert len(result.edges) == 1
        assert len(result.errors) == 1

    def test_result_mutable_lists(self):
        """Test that result lists are mutable."""
        result = ParseResult(file_path="test.py")
        result.nodes.append(
            ParsedNode(node_type="class", name="C", start_line=1, end_line=10)
        )
        result.edges.append(
            ParsedEdge(source_name="a", target_name="b", edge_type="references")
        )
        result.errors.append("Error!")

        assert len(result.nodes) == 1
        assert len(result.edges) == 1
        assert len(result.errors) == 1


class TestBaseParser:
    """Tests for BaseParser abstract base class."""

    def test_cannot_instantiate_abstract(self):
        """Test that BaseParser cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseParser()

    def test_mock_parser_properties(self):
        """Test mock parser property implementations."""
        parser = MockParser()
        assert parser.language_name == "mock"
        assert parser.file_extensions == [".mock", ".mk"]

    def test_get_node_text(self):
        """Test extracting text from a mock node."""
        parser = MockParser()
        source = b"hello world"

        class MockNode:
            start_byte = 0
            end_byte = 5

        node = MockNode()
        text = parser.get_node_text(node, source)
        assert text == "hello"

    def test_get_node_text_unicode(self):
        """Test extracting unicode text from a node."""
        parser = MockParser()
        source = "def hello_\u4e16\u754c():".encode("utf-8")

        class MockNode:
            start_byte = 4
            end_byte = len("def hello_\u4e16\u754c".encode("utf-8"))

        node = MockNode()
        text = parser.get_node_text(node, source)
        assert text == "hello_\u4e16\u754c"


class TestBaseParserAbstractMethods:
    """Test that abstract methods must be implemented."""

    def test_missing_language_name(self):
        """Test that language_name must be implemented."""

        class IncompleteParser(BaseParser):
            @property
            def file_extensions(self) -> list[str]:
                return [".test"]

            def _load_language(self):
                pass

            def extract_symbols(self, tree, source):
                return []

            def extract_references(self, tree, source):
                return []

        with pytest.raises(TypeError):
            IncompleteParser()

    def test_missing_file_extensions(self):
        """Test that file_extensions must be implemented."""

        class IncompleteParser(BaseParser):
            @property
            def language_name(self) -> str:
                return "test"

            def _load_language(self):
                pass

            def extract_symbols(self, tree, source):
                return []

            def extract_references(self, tree, source):
                return []

        with pytest.raises(TypeError):
            IncompleteParser()

    def test_missing_extract_symbols(self):
        """Test that extract_symbols must be implemented."""

        class IncompleteParser(BaseParser):
            @property
            def language_name(self) -> str:
                return "test"

            @property
            def file_extensions(self) -> list[str]:
                return [".test"]

            def _load_language(self):
                pass

            def extract_references(self, tree, source):
                return []

        with pytest.raises(TypeError):
            IncompleteParser()

    def test_missing_extract_references(self):
        """Test that extract_references must be implemented."""

        class IncompleteParser(BaseParser):
            @property
            def language_name(self) -> str:
                return "test"

            @property
            def file_extensions(self) -> list[str]:
                return [".test"]

            def _load_language(self):
                pass

            def extract_symbols(self, tree, source):
                return []

        with pytest.raises(TypeError):
            IncompleteParser()
