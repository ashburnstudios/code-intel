"""Base parser interface for tree-sitter based AST parsing."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Parser, Tree


@dataclass
class ParsedNode:
    """A code entity extracted from source.

    Represents a symbol definition found during parsing, such as a function,
    class, method, or variable declaration.
    """

    node_type: str
    """Type of the node: 'function', 'class', 'method', 'variable', etc."""

    name: str
    """The symbol name."""

    start_line: int
    """Starting line number (1-indexed)."""

    end_line: int
    """Ending line number (1-indexed)."""

    signature: str | None = None
    """Function/method signature, if applicable."""

    docstring: str | None = None
    """Documentation string, if present."""

    start_column: int = 0
    """Starting column (0-indexed)."""

    end_column: int = 0
    """Ending column (0-indexed)."""

    qualified_name: str | None = None
    """Fully qualified name (e.g., 'module.Class.method')."""

    metadata: dict = field(default_factory=dict)
    """Additional language-specific metadata."""


@dataclass
class ParsedEdge:
    """A relationship between code entities.

    Represents a connection found during parsing, such as a function call,
    import statement, or inheritance relationship.
    """

    source_name: str
    """Name of the source symbol (the one making the reference)."""

    target_name: str
    """Name of the target symbol (the one being referenced)."""

    edge_type: str
    """Type of relationship: 'calls', 'imports', 'inherits', 'references'."""

    source_location: tuple[int, int] | None = None
    """(line, column) where the relationship originates."""

    metadata: dict = field(default_factory=dict)
    """Additional edge metadata."""


@dataclass
class ParseResult:
    """Result of parsing a source file.

    Contains all extracted nodes (symbol definitions) and edges
    (relationships between symbols) from a single file.
    """

    file_path: str
    """Path to the parsed file."""

    nodes: list[ParsedNode] = field(default_factory=list)
    """All symbol definitions found in the file."""

    edges: list[ParsedEdge] = field(default_factory=list)
    """All relationships found in the file."""

    errors: list[str] = field(default_factory=list)
    """Any parsing errors encountered."""


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
        """Return the name of the language this parser handles.

        Examples: 'python', 'typescript', 'csharp'
        """
        ...

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]:
        """Return the file extensions this parser handles.

        Extensions should include the leading dot.
        Examples: ['.py', '.pyi'], ['.ts', '.tsx']
        """
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

    def parse_to_result(self, file_path: Path | str, content: str | None = None) -> ParseResult:
        """Parse a source file and extract nodes/edges as a ParseResult.

        This is the high-level parsing interface that returns structured
        data ready for graph construction.

        Args:
            file_path: Path to the source file.
            content: Optional source content. If not provided, reads from file_path.

        Returns:
            ParseResult containing extracted nodes, edges, and any errors.
        """
        file_path = Path(file_path)

        if content is None:
            source = file_path.read_bytes()
        else:
            source = content.encode("utf-8") if isinstance(content, str) else content

        tree = self.parse(source)

        # Check for syntax errors
        errors: list[str] = []
        if tree.root_node.has_error:
            errors.append(f"Syntax errors detected in {file_path}")

        # Extract symbols and convert to ParsedNode
        nodes: list[ParsedNode] = []
        symbols = self.extract_symbols(tree, source)
        for sym in symbols:
            node = ParsedNode(
                node_type=sym.get("kind", "unknown"),
                name=sym["name"],
                start_line=sym.get("line", sym.get("start_line", 1)),
                end_line=sym.get("end_line", sym.get("line", 1)),
                signature=sym.get("signature"),
                docstring=sym.get("docstring"),
                start_column=sym.get("start_column", 0),
                end_column=sym.get("end_column", 0),
                qualified_name=sym.get("qualified_name"),
                metadata=sym.get("metadata", {}),
            )
            nodes.append(node)

        # Extract references and convert to ParsedEdge
        edges: list[ParsedEdge] = []
        references = self.extract_references(tree, source)
        for ref in references:
            edge = ParsedEdge(
                source_name=ref.get("source", ref.get("from", "")),
                target_name=ref.get("target", ref.get("name", "")),
                edge_type=ref.get("type", "references"),
                source_location=(ref.get("line"), ref.get("column"))
                if "line" in ref
                else None,
                metadata=ref.get("metadata", {}),
            )
            edges.append(edge)

        return ParseResult(
            file_path=str(file_path),
            nodes=nodes,
            edges=edges,
            errors=errors,
        )
