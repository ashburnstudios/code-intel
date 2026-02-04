"""Schema definitions for performance profiles."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProfileType(str, Enum):
    """Types of profiles supported."""

    SAMPLED = "sampled"
    EVENTED = "evented"


class ValueUnit(str, Enum):
    """Units for profile measurements."""

    NANOSECONDS = "nanoseconds"
    MICROSECONDS = "microseconds"
    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"
    BYTES = "bytes"
    NONE = "none"


class Frame(BaseModel):
    """A frame in a profile (represents a function/method).

    Frames are stored separately and referenced by index in samples.
    """

    name: str = Field(description="Function/method name")
    file: str | None = Field(default=None, description="Source file path")
    line: int | None = Field(default=None, description="Line number")
    col: int | None = Field(default=None, description="Column number")

    def to_qualified_name(self) -> str:
        """Generate a qualified name for matching against code graph.

        Returns a string that can be used to look up this frame in the
        code-intel symbol graph.
        """
        # Parse common frame name formats:
        # - C#: Namespace.Class.Method(args)
        # - Python: module.function or Class.method
        # - JavaScript: function or Class.prototype.method
        name = self.name

        # Strip argument lists for matching
        if "(" in name:
            name = name.split("(")[0]

        return name


class FunctionStats(BaseModel):
    """Aggregated statistics for a function across a profile.

    This provides a summary view of a function's performance without
    needing to load the entire profile.
    """

    profile_id: str = Field(description="ID of the parent profile")
    frame_index: int = Field(description="Index into the profile's frames array")
    name: str = Field(description="Function name (denormalised for querying)")
    file: str | None = Field(default=None, description="Source file path")
    line: int | None = Field(default=None, description="Line number")

    # Timing metrics
    self_weight: float = Field(
        default=0.0,
        description="Time spent in this function only (excluding callees)",
    )
    total_weight: float = Field(
        default=0.0,
        description="Total time including callees",
    )
    call_count: int = Field(
        default=0,
        description="Number of times this function appears in samples",
    )

    # Percentage metrics (computed)
    self_percentage: float = Field(
        default=0.0,
        description="Self time as percentage of total profile time",
    )
    total_percentage: float = Field(
        default=0.0,
        description="Total time as percentage of total profile time",
    )

    # Code graph correlation
    symbol_id: str | None = Field(
        default=None,
        description="ID of the corresponding node in the code graph",
    )


class ProfileMetadata(BaseModel):
    """Metadata about a profile for identification and comparison."""

    commit_sha: str | None = Field(
        default=None, description="Git commit SHA at profile time"
    )
    scenario: str | None = Field(
        default=None, description="Test scenario name (e.g., 'startup', 'heavy-load')"
    )
    tags: list[str] = Field(
        default_factory=list, description="Arbitrary tags for grouping"
    )
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class Profile(BaseModel):
    """A complete performance profile.

    Represents all the data from a single profiling session, including
    frames, samples, and aggregated statistics.
    """

    id: str = Field(description="Unique identifier for this profile")
    name: str = Field(description="Human-readable profile name")
    profile_type: ProfileType = Field(description="Type of profile (sampled/evented)")
    unit: ValueUnit = Field(description="Unit of measurement")

    # Timing bounds
    start_value: float = Field(default=0.0, description="Start of profile window")
    end_value: float = Field(default=0.0, description="End of profile window")

    # The actual data
    frames: list[Frame] = Field(
        default_factory=list, description="All unique frames in this profile"
    )

    # Pre-computed statistics for fast querying
    function_stats: list[FunctionStats] = Field(
        default_factory=list, description="Aggregated stats per function"
    )

    # Metadata for identification and comparison
    metadata: ProfileMetadata = Field(
        default_factory=ProfileMetadata, description="Profile metadata"
    )

    # Storage metadata
    repo_path: str | None = Field(
        default=None, description="Repository path this profile is associated with"
    )
    source_file: str | None = Field(
        default=None, description="Original profile file path"
    )
    created_at: str | None = Field(default=None, description="When profile was ingested")

    @property
    def duration(self) -> float:
        """Total duration of the profile in the profile's unit."""
        return self.end_value - self.start_value

    def get_hotspots(self, limit: int = 10, by: str = "self") -> list[FunctionStats]:
        """Get the top functions by time spent.

        Args:
            limit: Maximum number of results.
            by: Sort key - 'self' for self time, 'total' for total time.

        Returns:
            List of FunctionStats sorted by the specified metric.
        """
        if by == "total":
            sorted_stats = sorted(
                self.function_stats, key=lambda s: s.total_weight, reverse=True
            )
        else:
            sorted_stats = sorted(
                self.function_stats, key=lambda s: s.self_weight, reverse=True
            )
        return sorted_stats[:limit]


class FunctionDelta(BaseModel):
    """Change in a function's performance between two profiles."""

    name: str = Field(description="Function name")
    file: str | None = Field(default=None, description="Source file")

    # Before values
    before_self_weight: float = Field(default=0.0)
    before_total_weight: float = Field(default=0.0)
    before_call_count: int = Field(default=0)

    # After values
    after_self_weight: float = Field(default=0.0)
    after_total_weight: float = Field(default=0.0)
    after_call_count: int = Field(default=0)

    # Deltas
    self_weight_delta: float = Field(default=0.0)
    total_weight_delta: float = Field(default=0.0)
    self_weight_change_pct: float | None = Field(
        default=None, description="Percentage change in self weight"
    )
    total_weight_change_pct: float | None = Field(
        default=None, description="Percentage change in total weight"
    )


class FrameSymbolMapping(BaseModel):
    """Cached mapping between a frame name and a code graph symbol.

    This caches the correlation between profile frame names (from speedscope, etc.)
    and code-intel symbol node IDs. The cache allows reuse across profiles and
    tracks the confidence of fuzzy matches.
    """

    frame_name: str = Field(description="The frame name as it appears in profiles")
    symbol_id: str | None = Field(
        default=None,
        description="ID of the corresponding node in the code graph",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Match confidence (1.0 = exact, lower = fuzzy)",
    )
    last_updated: str | None = Field(
        default=None,
        description="ISO8601 timestamp of last update",
    )


class ProfileComparison(BaseModel):
    """Comparison between two profiles."""

    before_profile_id: str = Field(description="ID of the 'before' profile")
    after_profile_id: str = Field(description="ID of the 'after' profile")
    before_profile_name: str = Field(description="Name of the 'before' profile")
    after_profile_name: str = Field(description="Name of the 'after' profile")

    # Overall metrics
    before_duration: float = Field(description="Duration of 'before' profile")
    after_duration: float = Field(description="Duration of 'after' profile")
    duration_delta: float = Field(description="Change in duration")
    duration_change_pct: float | None = Field(
        default=None, description="Percentage change in duration"
    )

    # Per-function deltas
    regressions: list[FunctionDelta] = Field(
        default_factory=list,
        description="Functions that got slower (sorted by impact)",
    )
    improvements: list[FunctionDelta] = Field(
        default_factory=list,
        description="Functions that got faster (sorted by impact)",
    )
    new_functions: list[FunctionStats] = Field(
        default_factory=list,
        description="Functions only in 'after' profile",
    )
    removed_functions: list[FunctionStats] = Field(
        default_factory=list,
        description="Functions only in 'before' profile",
    )


# =============================================================================
# Temporal Analysis Models (CINT-27)
# =============================================================================


class QuartileTrend(BaseModel):
    """Performance trend across time quartiles within a single profile.

    Used to detect within-session degradation by comparing early (Q1) vs
    late (Q4) execution periods.
    """

    function: str = Field(description="Function name")
    file: str | None = Field(default=None, description="Source file path")
    q1_avg_ms: float = Field(description="Average time in first quartile (ms)")
    q2_avg_ms: float = Field(description="Average time in second quartile (ms)")
    q3_avg_ms: float = Field(description="Average time in third quartile (ms)")
    q4_avg_ms: float = Field(description="Average time in fourth quartile (ms)")
    degradation_factor: float = Field(
        description="Ratio of Q4 to Q1 time (>1 means slower over time)"
    )
    sample_count: int = Field(
        default=0, description="Total number of samples for this function"
    )
    is_degraded: bool = Field(
        default=False,
        description="True if function shows significant degradation (Q4/Q1 > threshold)",
    )


class DegradationReport(BaseModel):
    """Report of within-session performance degradation.

    Analyses a single profile by splitting it into time quartiles
    to detect functions that get slower during execution.
    """

    profile_id: str = Field(description="ID of the analysed profile")
    profile_name: str = Field(description="Name of the analysed profile")
    has_degradation: bool = Field(
        description="True if any significant degradation detected"
    )
    degraded_functions: list[QuartileTrend] = Field(
        default_factory=list,
        description="Functions showing degradation (sorted by severity)",
    )
    stable_functions: list[QuartileTrend] = Field(
        default_factory=list,
        description="Functions with consistent performance",
    )
    total_functions_analysed: int = Field(
        default=0, description="Total functions analysed"
    )
    degradation_threshold: float = Field(
        default=1.5, description="Q4/Q1 ratio threshold used for detection"
    )
    summary: str = Field(default="", description="Human-readable summary for LLMs")


class Regression(BaseModel):
    """A performance regression between a baseline and comparison profile."""

    function: str = Field(description="Function name")
    file: str | None = Field(default=None, description="Source file path")
    baseline_self_ms: float = Field(description="Self time in baseline (ms)")
    comparison_self_ms: float = Field(description="Self time in comparison (ms)")
    change_pct: float = Field(description="Percentage change in self time")
    absolute_change_ms: float = Field(description="Absolute change in self time (ms)")
    baseline_profile_id: str = Field(description="ID of the baseline profile")
    comparison_profile_id: str = Field(description="ID of the comparison profile")
    comparison_commit: str | None = Field(
        default=None, description="Commit SHA of comparison profile"
    )
    is_significant: bool = Field(
        default=True, description="True if regression exceeds threshold"
    )


class RegressionReport(BaseModel):
    """Report of regressions across multiple profiles compared to a baseline."""

    baseline_profile_id: str = Field(description="ID of the baseline profile")
    baseline_profile_name: str = Field(description="Name of the baseline profile")
    baseline_commit: str | None = Field(
        default=None, description="Commit SHA of baseline profile"
    )
    comparison_count: int = Field(description="Number of profiles compared")
    regressions: list[Regression] = Field(
        default_factory=list,
        description="Detected regressions (sorted by severity)",
    )
    improvements: list[Regression] = Field(
        default_factory=list,
        description="Detected improvements (sorted by impact)",
    )
    threshold_pct: float = Field(
        default=20.0, description="Percentage threshold used for detection"
    )
    summary: str = Field(default="", description="Human-readable summary for LLMs")


class Anomaly(BaseModel):
    """A function with anomalous timing variance."""

    function: str = Field(description="Function name")
    file: str | None = Field(default=None, description="Source file path")
    mean_ms: float = Field(description="Mean execution time (ms)")
    std_dev_ms: float = Field(description="Standard deviation (ms)")
    min_ms: float = Field(description="Minimum execution time (ms)")
    max_ms: float = Field(description="Maximum execution time (ms)")
    coefficient_of_variation: float = Field(
        description="CV = std_dev / mean (higher = more variable)"
    )
    sample_count: int = Field(description="Number of samples")
    profile_id: str = Field(description="ID of the source profile")
    severity: str = Field(
        default="medium",
        description="Anomaly severity: 'low', 'medium', 'high'",
    )


class AnomalyReport(BaseModel):
    """Report of functions with unusual timing variance."""

    profile_id: str = Field(description="ID of the analysed profile")
    profile_name: str = Field(description="Name of the analysed profile")
    anomalies: list[Anomaly] = Field(
        default_factory=list,
        description="Functions with high variance (sorted by severity)",
    )
    cv_threshold: float = Field(
        default=0.5,
        description="Coefficient of variation threshold used for detection",
    )
    min_samples: int = Field(
        default=5, description="Minimum samples required for analysis"
    )
    total_functions_analysed: int = Field(
        default=0, description="Total functions analysed"
    )
    summary: str = Field(default="", description="Human-readable summary for LLMs")
