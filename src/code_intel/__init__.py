"""Code-intel: Code graph intelligence for AI assistants."""

from code_intel.client import CodeIntelClient
from code_intel.graph.schema import (
    CodeGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)
from code_intel.parser.base import BaseParser

__version__ = "0.1.0"

__all__ = [
    "BaseParser",
    "CodeGraph",
    "CodeIntelClient",
    "EdgeKind",
    "GraphEdge",
    "GraphNode",
    "Location",
    "NodeKind",
]
