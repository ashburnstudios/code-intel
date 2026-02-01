"""Code-intel: Code graph intelligence for AI assistants."""

from code_intel.client import (
    CodeIntelClient,
    IndexResult,
    ProfileIngestResult,
    ProgressCallback,
    RepoStats,
)
from code_intel.graph.schema import (
    CodeGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)
from code_intel.graph.storage import GraphStorage
from code_intel.indexer.roslyn import (
    RoslynIndexer,
    RoslynIndexResult,
    RoslynProgressCallback,
)
from code_intel.lsp.omnisharp import (
    OmniSharpError,
    OmniSharpNotFoundError,
    OmniSharpServer,
    OmniSharpTimeoutError,
)
from code_intel.parser import get_python_parser
from code_intel.parser.base import BaseParser, ParsedEdge, ParsedNode, ParseResult
from code_intel.parser.registry import (
    ParserRegistry,
    get_global_registry,
    get_parser,
    get_parser_for_file,
    register_parser,
)
from code_intel.profile import (
    Frame,
    FrameSymbolMapping,
    FunctionDelta,
    FunctionStats,
    Profile,
    ProfileComparison,
    ProfileMetadata,
    ProfileStorage,
    ProfileType,
    SpeedscopeParser,
    ValueUnit,
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "CodeIntelClient",
    "IndexResult",
    "ProfileIngestResult",
    "ProgressCallback",
    "RepoStats",
    # Graph
    "CodeGraph",
    "EdgeKind",
    "GraphEdge",
    "GraphNode",
    "GraphStorage",
    "Location",
    "NodeKind",
    # Indexer (LSP-based)
    "RoslynIndexer",
    "RoslynIndexResult",
    "RoslynProgressCallback",
    # LSP
    "OmniSharpServer",
    "OmniSharpError",
    "OmniSharpNotFoundError",
    "OmniSharpTimeoutError",
    # Parser
    "BaseParser",
    "ParsedEdge",
    "ParsedNode",
    "ParseResult",
    "ParserRegistry",
    "get_global_registry",
    "get_parser",
    "get_parser_for_file",
    "get_python_parser",
    "register_parser",
    # Profile
    "Frame",
    "FrameSymbolMapping",
    "FunctionDelta",
    "FunctionStats",
    "Profile",
    "ProfileComparison",
    "ProfileMetadata",
    "ProfileStorage",
    "ProfileType",
    "SpeedscopeParser",
    "ValueUnit",
]
