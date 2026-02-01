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
