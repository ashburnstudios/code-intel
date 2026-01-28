"""Tests for the parser registry."""

import pytest
from pathlib import Path
from typing import TYPE_CHECKING

from code_intel.parser.base import BaseParser
from code_intel.parser.registry import (
    ParserRegistry,
    get_global_registry,
    get_parser,
    get_parser_for_file,
    register_parser,
)

if TYPE_CHECKING:
    from tree_sitter import Language, Tree


class MockPythonParser(BaseParser):
    """Mock Python parser for testing."""

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> list[str]:
        return [".py", ".pyi"]

    def _load_language(self) -> "Language":
        raise NotImplementedError()

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        return []

    def extract_references(self, tree: "Tree", source: bytes) -> list[dict]:
        return []


class MockTypeScriptParser(BaseParser):
    """Mock TypeScript parser for testing."""

    @property
    def language_name(self) -> str:
        return "typescript"

    @property
    def file_extensions(self) -> list[str]:
        return [".ts", ".tsx"]

    def _load_language(self) -> "Language":
        raise NotImplementedError()

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        return []

    def extract_references(self, tree: "Tree", source: bytes) -> list[dict]:
        return []


class MockDuplicateExtParser(BaseParser):
    """Parser with extension that conflicts with Python parser."""

    @property
    def language_name(self) -> str:
        return "fake-python"

    @property
    def file_extensions(self) -> list[str]:
        return [".py"]  # Conflicts with Python

    def _load_language(self) -> "Language":
        raise NotImplementedError()

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        return []

    def extract_references(self, tree: "Tree", source: bytes) -> list[dict]:
        return []


class TestParserRegistry:
    """Tests for ParserRegistry class."""

    def test_empty_registry(self):
        """Test empty registry properties."""
        registry = ParserRegistry()
        assert len(registry) == 0
        assert registry.languages == []
        assert registry.extensions == []

    def test_register_parser(self):
        """Test registering a parser."""
        registry = ParserRegistry()
        parser = MockPythonParser()

        registry.register(parser)

        assert len(registry) == 1
        assert "python" in registry
        assert ".py" in registry.extensions
        assert ".pyi" in registry.extensions

    def test_register_multiple_parsers(self):
        """Test registering multiple parsers."""
        registry = ParserRegistry()
        registry.register(MockPythonParser())
        registry.register(MockTypeScriptParser())

        assert len(registry) == 2
        assert "python" in registry
        assert "typescript" in registry
        assert set(registry.extensions) == {".py", ".pyi", ".ts", ".tsx"}

    def test_register_duplicate_language(self):
        """Test that registering duplicate language raises error."""
        registry = ParserRegistry()
        registry.register(MockPythonParser())

        with pytest.raises(ValueError, match="already registered"):
            registry.register(MockPythonParser())

    def test_register_duplicate_extension(self):
        """Test that registering duplicate extension raises error."""
        registry = ParserRegistry()
        registry.register(MockPythonParser())

        with pytest.raises(ValueError, match="already mapped"):
            registry.register(MockDuplicateExtParser())

    def test_get_parser_by_language(self):
        """Test getting parser by language name."""
        registry = ParserRegistry()
        python_parser = MockPythonParser()
        ts_parser = MockTypeScriptParser()

        registry.register(python_parser)
        registry.register(ts_parser)

        assert registry.get_parser("python") is python_parser
        assert registry.get_parser("typescript") is ts_parser
        assert registry.get_parser("unknown") is None

    def test_get_parser_by_extension(self):
        """Test getting parser by file extension."""
        registry = ParserRegistry()
        python_parser = MockPythonParser()

        registry.register(python_parser)

        # With dot
        assert registry.get_parser_for_extension(".py") is python_parser
        assert registry.get_parser_for_extension(".pyi") is python_parser

        # Without dot
        assert registry.get_parser_for_extension("py") is python_parser

        # Case insensitive
        assert registry.get_parser_for_extension(".PY") is python_parser
        assert registry.get_parser_for_extension("PY") is python_parser

        # Unknown
        assert registry.get_parser_for_extension(".js") is None

    def test_get_parser_for_file(self):
        """Test getting parser for a file path."""
        registry = ParserRegistry()
        python_parser = MockPythonParser()
        ts_parser = MockTypeScriptParser()

        registry.register(python_parser)
        registry.register(ts_parser)

        # String paths
        assert registry.get_parser_for_file("main.py") is python_parser
        assert registry.get_parser_for_file("types.pyi") is python_parser
        assert registry.get_parser_for_file("app.ts") is ts_parser
        assert registry.get_parser_for_file("Component.tsx") is ts_parser

        # Path objects
        assert registry.get_parser_for_file(Path("src/main.py")) is python_parser
        assert registry.get_parser_for_file(Path("/abs/path/app.ts")) is ts_parser

        # Unknown extension
        assert registry.get_parser_for_file("readme.md") is None

    def test_unregister_parser(self):
        """Test unregistering a parser."""
        registry = ParserRegistry()
        registry.register(MockPythonParser())
        registry.register(MockTypeScriptParser())

        registry.unregister("python")

        assert len(registry) == 1
        assert "python" not in registry
        assert "typescript" in registry
        assert ".py" not in registry.extensions
        assert ".ts" in registry.extensions

    def test_unregister_unknown_language(self):
        """Test unregistering unknown language raises error."""
        registry = ParserRegistry()

        with pytest.raises(KeyError, match="No parser registered"):
            registry.unregister("unknown")

    def test_contains(self):
        """Test __contains__ method."""
        registry = ParserRegistry()
        registry.register(MockPythonParser())

        assert "python" in registry
        assert "typescript" not in registry

    def test_extension_normalisation(self):
        """Test that extensions are normalised to lowercase with dot."""

        class WeirdExtParser(BaseParser):
            @property
            def language_name(self) -> str:
                return "weird"

            @property
            def file_extensions(self) -> list[str]:
                return ["WEIRD", ".WeIrD2"]  # No dot, mixed case

            def _load_language(self):
                raise NotImplementedError()

            def extract_symbols(self, tree, source):
                return []

            def extract_references(self, tree, source):
                return []

        registry = ParserRegistry()
        parser = WeirdExtParser()
        registry.register(parser)

        # All lookups should work regardless of case/dot
        assert registry.get_parser_for_extension(".weird") is parser
        assert registry.get_parser_for_extension("weird") is parser
        assert registry.get_parser_for_extension(".WEIRD") is parser
        assert registry.get_parser_for_extension(".weird2") is parser
        assert registry.get_parser_for_extension("WEIRD2") is parser


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_get_global_registry_singleton(self):
        """Test that global registry is a singleton."""
        reg1 = get_global_registry()
        reg2 = get_global_registry()
        assert reg1 is reg2

    def test_register_parser_global(self):
        """Test registering parser via global function."""
        # Note: This modifies global state, so we need to be careful
        registry = get_global_registry()
        initial_count = len(registry)

        class TestParser(BaseParser):
            @property
            def language_name(self) -> str:
                return "test-global"

            @property
            def file_extensions(self) -> list[str]:
                return [".testglobal"]

            def _load_language(self):
                raise NotImplementedError()

            def extract_symbols(self, tree, source):
                return []

            def extract_references(self, tree, source):
                return []

        try:
            register_parser(TestParser())
            assert len(registry) == initial_count + 1
            assert "test-global" in registry
        finally:
            # Cleanup
            registry.unregister("test-global")

    def test_get_parser_global(self):
        """Test getting parser via global function."""
        registry = get_global_registry()

        class TestParser2(BaseParser):
            @property
            def language_name(self) -> str:
                return "test-global-2"

            @property
            def file_extensions(self) -> list[str]:
                return [".testglobal2"]

            def _load_language(self):
                raise NotImplementedError()

            def extract_symbols(self, tree, source):
                return []

            def extract_references(self, tree, source):
                return []

        try:
            parser = TestParser2()
            register_parser(parser)
            assert get_parser("test-global-2") is parser
            assert get_parser("nonexistent") is None
        finally:
            registry.unregister("test-global-2")

    def test_get_parser_for_file_global(self):
        """Test getting parser for file via global function."""
        registry = get_global_registry()

        class TestParser3(BaseParser):
            @property
            def language_name(self) -> str:
                return "test-global-3"

            @property
            def file_extensions(self) -> list[str]:
                return [".testglobal3"]

            def _load_language(self):
                raise NotImplementedError()

            def extract_symbols(self, tree, source):
                return []

            def extract_references(self, tree, source):
                return []

        try:
            parser = TestParser3()
            register_parser(parser)
            assert get_parser_for_file("file.testglobal3") is parser
            assert get_parser_for_file(Path("dir/file.testglobal3")) is parser
            assert get_parser_for_file("file.unknown") is None
        finally:
            registry.unregister("test-global-3")


class TestTopLevelExports:
    """Test that new exports are available from package root."""

    def test_parser_module_exports(self):
        """Test exports from parser module."""
        from code_intel.parser import (
            BaseParser,
            ParsedEdge,
            ParsedNode,
            ParseResult,
            ParserRegistry,
            get_global_registry,
            get_parser,
            get_parser_for_file,
            register_parser,
        )

        assert BaseParser is not None
        assert ParsedNode is not None
        assert ParsedEdge is not None
        assert ParseResult is not None
        assert ParserRegistry is not None

    def test_root_package_exports(self):
        """Test exports from root package."""
        from code_intel import (
            BaseParser,
            ParsedEdge,
            ParsedNode,
            ParseResult,
            ParserRegistry,
            get_global_registry,
            get_parser,
            get_parser_for_file,
            register_parser,
        )

        # Create instances to verify they work
        node = ParsedNode(
            node_type="function",
            name="test",
            start_line=1,
            end_line=5,
        )
        assert node.name == "test"

        edge = ParsedEdge(
            source_name="a",
            target_name="b",
            edge_type="calls",
        )
        assert edge.edge_type == "calls"

        result = ParseResult(file_path="test.py")
        assert result.file_path == "test.py"

        registry = ParserRegistry()
        assert len(registry) == 0
