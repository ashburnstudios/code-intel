"""Main client interface for code-intel."""

from pathlib import Path
from typing import TYPE_CHECKING

from code_intel.graph.schema import CodeGraph, GraphNode

if TYPE_CHECKING:
    from code_intel.parser.base import BaseParser


class CodeIntelClient:
    """Synchronous client for code intelligence operations.

    Provides methods for indexing codebases, finding callers/references,
    and performing impact analysis.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise the client.

        Args:
            db_path: Path to the SQLite database file. If None, uses
                     in-memory database.
        """
        self._db_path = Path(db_path) if db_path else None
        self._parsers: dict[str, "BaseParser"] = {}
        self._graph: CodeGraph = CodeGraph()

    def register_parser(self, parser: "BaseParser") -> None:
        """Register a parser for a specific language.

        Args:
            parser: Parser instance to register.
        """
        self._parsers[parser.language_name] = parser

    def index_file(self, path: Path | str, language: str | None = None) -> None:
        """Index a single file.

        Args:
            path: Path to the source file.
            language: Language name. If None, inferred from extension.

        Raises:
            ValueError: If no parser is registered for the language.
        """
        path = Path(path)
        if language is None:
            language = self._infer_language(path)

        if language not in self._parsers:
            raise ValueError(f"No parser registered for language: {language}")

        parser = self._parsers[language]
        tree = parser.parse_file(path)
        source = path.read_bytes()

        symbols = parser.extract_symbols(tree, source)
        for symbol in symbols:
            node = GraphNode(
                id=f"{path}:{symbol['name']}:{symbol['line']}",
                name=symbol["name"],
                kind=symbol["kind"],
                location=symbol["location"],
                qualified_name=symbol.get("qualified_name"),
                signature=symbol.get("signature"),
                docstring=symbol.get("docstring"),
            )
            self._graph.add_node(node)

    def index_directory(
        self,
        path: Path | str,
        extensions: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        """Index all files in a directory.

        Args:
            path: Root directory path.
            extensions: File extensions to include (e.g., ['.py', '.ts']).
            exclude_patterns: Glob patterns to exclude.
        """
        path = Path(path)
        exclude_patterns = exclude_patterns or []

        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue

            if extensions and file_path.suffix not in extensions:
                continue

            if any(file_path.match(p) for p in exclude_patterns):
                continue

            try:
                language = self._infer_language(file_path)
                if language in self._parsers:
                    self.index_file(file_path, language)
            except ValueError:
                # Skip files we can't parse
                pass

    def find_callers(self, symbol_name: str) -> list[GraphNode]:
        """Find all callers of a function/method.

        Args:
            symbol_name: Name of the function/method.

        Returns:
            List of nodes that call the specified symbol.
        """
        # Find the target node
        target_nodes = [n for n in self._graph.nodes if n.name == symbol_name]
        if not target_nodes:
            return []

        # Find edges pointing to these nodes with CALLS relationship
        callers = []
        for target in target_nodes:
            edges = self._graph.get_edges_to(target.id)
            for edge in edges:
                if edge.kind.value == "calls":
                    caller = self._graph.get_node(edge.source_id)
                    if caller:
                        callers.append(caller)

        return callers

    def find_references(self, symbol_name: str) -> list[GraphNode]:
        """Find all references to a symbol.

        Args:
            symbol_name: Name of the symbol.

        Returns:
            List of locations where the symbol is referenced.
        """
        # Find the target node
        target_nodes = [n for n in self._graph.nodes if n.name == symbol_name]
        if not target_nodes:
            return []

        # Find all edges pointing to these nodes
        references = []
        for target in target_nodes:
            edges = self._graph.get_edges_to(target.id)
            for edge in edges:
                source = self._graph.get_node(edge.source_id)
                if source:
                    references.append(source)

        return references

    def get_symbol_info(self, symbol_name: str) -> GraphNode | None:
        """Get information about a symbol.

        Args:
            symbol_name: Name of the symbol.

        Returns:
            GraphNode with symbol information, or None if not found.
        """
        for node in self._graph.nodes:
            if node.name == symbol_name:
                return node
        return None

    def _infer_language(self, path: Path) -> str:
        """Infer language from file extension.

        Args:
            path: File path.

        Returns:
            Language name.

        Raises:
            ValueError: If language cannot be inferred.
        """
        extension_map = {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".cs": "csharp",
        }

        language = extension_map.get(path.suffix.lower())
        if language is None:
            raise ValueError(f"Cannot infer language for extension: {path.suffix}")

        return language
