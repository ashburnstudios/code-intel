"""LSP-based indexing for code-intel.

This module provides integration with Language Server Protocol (LSP) servers,
specifically OmniSharp for C# semantic analysis.
"""

from code_intel.lsp.omnisharp import (
    OmniSharpError,
    OmniSharpNotFoundError,
    OmniSharpServer,
    OmniSharpTimeoutError,
)
from code_intel.lsp.protocol import (
    CodeElement,
    CodeStructureRequest,
    CodeStructureResponse,
    FindUsagesRequest,
    GotoDefinitionRequest,
    GotoDefinitionResponse,
    Location,
    OmniSharpRequest,
    OmniSharpResponse,
    Point,
    QuickFix,
    QuickFixResponse,
    Range,
)

__all__ = [
    # OmniSharp server
    "OmniSharpServer",
    "OmniSharpError",
    "OmniSharpNotFoundError",
    "OmniSharpTimeoutError",
    # Protocol types
    "CodeElement",
    "CodeStructureRequest",
    "CodeStructureResponse",
    "FindUsagesRequest",
    "GotoDefinitionRequest",
    "GotoDefinitionResponse",
    "Location",
    "OmniSharpRequest",
    "OmniSharpResponse",
    "Point",
    "QuickFix",
    "QuickFixResponse",
    "Range",
]
