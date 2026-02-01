"""Profile analysis module for code-intel.

This module provides functionality for ingesting, storing, and querying
performance profile data (e.g., from speedscope, py-spy, dotnet-trace).
"""

from code_intel.profile.schema import (
    Frame,
    FrameSymbolMapping,
    FunctionDelta,
    FunctionStats,
    Profile,
    ProfileComparison,
    ProfileMetadata,
    ProfileType,
    ValueUnit,
)
from code_intel.profile.speedscope import SpeedscopeParser
from code_intel.profile.storage import ProfileStorage

__all__ = [
    # Schema
    "Frame",
    "FrameSymbolMapping",
    "FunctionDelta",
    "FunctionStats",
    "Profile",
    "ProfileComparison",
    "ProfileMetadata",
    "ProfileType",
    "ValueUnit",
    # Parser
    "SpeedscopeParser",
    # Storage
    "ProfileStorage",
]
