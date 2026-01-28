"""Base parser interface for tree-sitter based AST parsing."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Parser, Tree


class BaseParser(ABC):
    """Abstract base class for language-specific parsers.

    Provides common interface for parsing source code and extracting
    semantic information using tree-sitter.
    """

    def __init__(self) -> None:
        """Initialise the parser with the language grammar."""
        self._parser: Parser | None = None
        self._language: Language | None = None

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Return the name of the language this parser handles."""
        ...

    @abstractmethod
    def _load_language(self) -> "Language":
        """Load and return the tree-sitter language grammar.

        Subclasses must implement this to load their specific grammar.
        """
        ...

    def _ensure_parser(self) -> "Parser":
        """Lazily initialise the tree-sitter parser."""
        if self._parser is None:
            from tree_sitter import Parser

            self._language = self._load_language()
            self._parser = Parser(self._language)
        return self._parser

    def parse(self, source: str | bytes) -> "Tree":
        """Parse source code and return the AST.

        Args:
            source: Source code as string or bytes.

        Returns:
            Tree-sitter Tree object representing the AST.
        """
        parser = self._ensure_parser()
        if isinstance(source, str):
            source = source.encode("utf-8")
        return parser.parse(source)

    def parse_file(self, path: Path | str) -> "Tree":
        """Parse a file and return the AST.

        Args:
            path: Path to the source file.

        Returns:
            Tree-sitter Tree object representing the AST.
        """
        path = Path(path)
        source = path.read_bytes()
        return self.parse(source)

    @abstractmethod
    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol definitions from the AST.

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes (for extracting text).

        Returns:
            List of symbol dictionaries with name, kind, location, etc.
        """
        ...

    @abstractmethod
    def extract_references(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol references from the AST.

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes (for extracting text).

        Returns:
            List of reference dictionaries with name, location, etc.
        """
        ...

    def get_node_text(self, node: "Node", source: bytes) -> str:
        """Extract the text content of a node.

        Args:
            node: Tree-sitter Node.
            source: Original source bytes.

        Returns:
            The text content of the node as a string.
        """
        return source[node.start_byte : node.end_byte].decode("utf-8")
