"""Tree-sitter based AST parsing for multiple languages."""

from code_intel.parser.base import BaseParser, ParsedEdge, ParsedNode, ParseResult
from code_intel.parser.registry import (
    ParserRegistry,
    get_global_registry,
    get_parser,
    get_parser_for_file,
    register_parser,
)

# Language-specific parsers (lazy imports to avoid requiring all grammars)
def get_python_parser():
    """Get the Python parser instance.

    Returns:
        PythonParser instance.

    Raises:
        ImportError: If tree-sitter-python is not installed.
    """
    from code_intel.parser.python import PythonParser
    return PythonParser()


def get_csharp_parser():
    """Get the C# parser instance.

    Returns:
        CSharpParser instance.

    Raises:
        ImportError: If tree-sitter-c-sharp is not installed.
    """
    from code_intel.parser.csharp import CSharpParser
    return CSharpParser()


def get_xaml_parser():
    """Get the XAML parser instance.

    Returns:
        XamlParser instance.

    Note:
        Unlike tree-sitter based parsers, XamlParser uses Python's
        xml.etree.ElementTree since XAML is well-formed XML.
    """
    from code_intel.parser.xaml import XamlParser
    return XamlParser()


def get_go_parser():
    """Get the Go parser instance.

    Returns:
        GoParser instance.

    Raises:
        ImportError: If tree-sitter-go is not installed.
    """
    from code_intel.parser.go import GoParser
    return GoParser()


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
    # Parser factory functions
    "get_python_parser",
    "get_csharp_parser",
    "get_xaml_parser",
    "get_go_parser",
]
