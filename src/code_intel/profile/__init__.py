"""Profile analysis module for code-intel.

This module provides functionality for ingesting, storing, and querying
performance profile data (e.g., from speedscope, py-spy, dotnet-trace).
"""

from code_intel.profile.schema import (
    Anomaly,
    AnomalyReport,
    DegradationReport,
    Frame,
    FrameSymbolMapping,
    FunctionDelta,
    FunctionStats,
    Profile,
    ProfileComparison,
    ProfileMetadata,
    ProfileType,
    QuartileTrend,
    Regression,
    RegressionReport,
    ValueUnit,
)
from code_intel.profile.speedscope import SpeedscopeParser
from code_intel.profile.storage import ProfileStorage
from code_intel.profile.temporal import TemporalAnalyser

__all__ = [
    # Schema
    "Anomaly",
    "AnomalyReport",
    "DegradationReport",
    "Frame",
    "FrameSymbolMapping",
    "FunctionDelta",
    "FunctionStats",
    "Profile",
    "ProfileComparison",
    "ProfileMetadata",
    "ProfileType",
    "QuartileTrend",
    "Regression",
    "RegressionReport",
    "ValueUnit",
    # Parser
    "SpeedscopeParser",
    # Storage
    "ProfileStorage",
    # Temporal Analysis (CINT-27)
    "TemporalAnalyser",
]
