"""Tree-sitter based AST parsing for multiple languages."""

from code_intel.parser.base import BaseParser, ParsedEdge, ParsedNode, ParseResult
from code_intel.parser.registry import (
    ParserRegistry,
    get_global_registry,
    get_parser,
    get_parser_for_file,
    register_parser,
)

__all__ = [
    # Base classes and dataclasses
    "BaseParser",
    "ParsedEdge",
    "ParsedNode",
    "ParseResult",
    # Registry
    "ParserRegistry",
    "get_global_registry",
    "get_parser",
    "get_parser_for_file",
    "register_parser",
]
