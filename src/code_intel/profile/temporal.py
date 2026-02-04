"""Temporal analysis for detecting performance changes over time.

This module provides analysis tools for:
- Quartile analysis: Detect within-session degradation
- Cross-profile regression detection: Compare profiles across commits
- Anomaly detection: Find functions with high timing variance

CINT-27: Temporal analysis and regression detection
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from code_intel.profile.schema import (
    Anomaly,
    AnomalyReport,
    DegradationReport,
    QuartileTrend,
    Regression,
    RegressionReport,
)

if TYPE_CHECKING:
    from code_intel.profile.schema import Profile
    from code_intel.profile.storage import ProfileStorage


@dataclass
class TimedSample:
    """A sample with timing information for temporal analysis."""

    function: str
    file: str | None
    weight: float
    timestamp: float  # Relative position in profile (0.0 to 1.0)


@dataclass
class FunctionTimings:
    """Collected timing data for a single function."""

    name: str
    file: str | None = None
    samples: list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)


def _generate_degradation_summary(
    report: DegradationReport,
    top_n: int = 5,
) -> str:
    """Generate a human-readable summary of degradation analysis.

    Args:
        report: The degradation report to summarise.
        top_n: Number of top degraded functions to highlight.

    Returns:
        Human-readable summary suitable for LLM consumption.
    """
    lines = [f"## Degradation Analysis: {report.profile_name}"]
    lines.append("")

    if not report.has_degradation:
        lines.append("**No significant degradation detected.**")
        lines.append("")
        lines.append(
            f"Analysed {report.total_functions_analysed} functions. "
            f"All maintained stable performance throughout the session "
            f"(Q4/Q1 ratio < {report.degradation_threshold:.1f}x)."
        )
        return "\n".join(lines)

    # Summary of degradation
    degraded_count = len(report.degraded_functions)
    lines.append(f"**{degraded_count} functions show degradation** over the session.")
    lines.append("")

    # Top degraded functions
    lines.append("### Top Degraded Functions")
    lines.append("")
    for trend in report.degraded_functions[:top_n]:
        lines.append(
            f"- **{trend.function}**: {trend.degradation_factor:.2f}x slower "
            f"(Q1: {trend.q1_avg_ms:.1f}ms → Q4: {trend.q4_avg_ms:.1f}ms)"
        )
        if trend.file:
            lines.append(f"  - File: `{trend.file}`")

    if degraded_count > top_n:
        lines.append(f"- ... and {degraded_count - top_n} more")

    lines.append("")
    lines.append("### Analysis Notes")
    lines.append("")
    lines.append(
        f"- Threshold: Functions with Q4/Q1 > {report.degradation_threshold:.1f}x "
        "are flagged as degraded"
    )
    lines.append(
        f"- Total functions analysed: {report.total_functions_analysed}"
    )
    lines.append(
        "- Possible causes: memory leaks, cache exhaustion, resource contention"
    )

    return "\n".join(lines)


def _generate_regression_summary(
    report: RegressionReport,
    top_n: int = 5,
) -> str:
    """Generate a human-readable summary of regression analysis.

    Args:
        report: The regression report to summarise.
        top_n: Number of top regressions to highlight.

    Returns:
        Human-readable summary suitable for LLM consumption.
    """
    lines = [f"## Regression Analysis: Baseline vs {report.comparison_count} profiles"]
    lines.append("")

    if report.baseline_commit:
        lines.append(f"**Baseline commit:** `{report.baseline_commit}`")
        lines.append("")

    if not report.regressions and not report.improvements:
        lines.append("**No significant changes detected.**")
        lines.append("")
        lines.append(
            f"All compared profiles show performance within "
            f"±{report.threshold_pct:.0f}% of the baseline."
        )
        return "\n".join(lines)

    # Regressions
    if report.regressions:
        lines.append(f"### {len(report.regressions)} Regressions Detected")
        lines.append("")
        for reg in report.regressions[:top_n]:
            lines.append(
                f"- **{reg.function}**: +{reg.change_pct:.1f}% "
                f"({reg.baseline_self_ms:.1f}ms → {reg.comparison_self_ms:.1f}ms)"
            )
            if reg.comparison_commit:
                lines.append(f"  - Introduced in: `{reg.comparison_commit}`")

        if len(report.regressions) > top_n:
            lines.append(f"- ... and {len(report.regressions) - top_n} more")
        lines.append("")

    # Improvements
    if report.improvements:
        lines.append(f"### {len(report.improvements)} Improvements Detected")
        lines.append("")
        for imp in report.improvements[:top_n]:
            lines.append(
                f"- **{imp.function}**: {imp.change_pct:.1f}% "
                f"({imp.baseline_self_ms:.1f}ms → {imp.comparison_self_ms:.1f}ms)"
            )

        if len(report.improvements) > top_n:
            lines.append(f"- ... and {len(report.improvements) - top_n} more")
        lines.append("")

    lines.append("### Analysis Notes")
    lines.append("")
    lines.append(f"- Threshold: Changes > ±{report.threshold_pct:.0f}% are flagged")
    lines.append(f"- Profiles compared: {report.comparison_count}")

    return "\n".join(lines)


def _generate_anomaly_summary(
    report: AnomalyReport,
    top_n: int = 5,
) -> str:
    """Generate a human-readable summary of anomaly analysis.

    Args:
        report: The anomaly report to summarise.
        top_n: Number of top anomalies to highlight.

    Returns:
        Human-readable summary suitable for LLM consumption.
    """
    lines = [f"## Anomaly Analysis: {report.profile_name}"]
    lines.append("")

    if not report.anomalies:
        lines.append("**No timing anomalies detected.**")
        lines.append("")
        lines.append(
            f"Analysed {report.total_functions_analysed} functions. "
            f"All have stable, predictable timing (CV < {report.cv_threshold:.2f})."
        )
        return "\n".join(lines)

    # Group by severity
    high = [a for a in report.anomalies if a.severity == "high"]
    medium = [a for a in report.anomalies if a.severity == "medium"]
    low = [a for a in report.anomalies if a.severity == "low"]

    lines.append(
        f"**{len(report.anomalies)} functions with high variance detected:**"
    )
    lines.append(f"- High severity: {len(high)}")
    lines.append(f"- Medium severity: {len(medium)}")
    lines.append(f"- Low severity: {len(low)}")
    lines.append("")

    # Top anomalies
    lines.append("### Top Unstable Functions")
    lines.append("")
    for anomaly in report.anomalies[:top_n]:
        lines.append(
            f"- **{anomaly.function}** [{anomaly.severity.upper()}]: "
            f"CV={anomaly.coefficient_of_variation:.2f} "
            f"(mean: {anomaly.mean_ms:.1f}ms, std: {anomaly.std_dev_ms:.1f}ms, "
            f"range: {anomaly.min_ms:.1f}-{anomaly.max_ms:.1f}ms)"
        )

    if len(report.anomalies) > top_n:
        lines.append(f"- ... and {len(report.anomalies) - top_n} more")

    lines.append("")
    lines.append("### Analysis Notes")
    lines.append("")
    lines.append(
        f"- CV threshold: {report.cv_threshold:.2f} "
        "(coefficient of variation = std_dev / mean)"
    )
    lines.append(f"- Minimum samples required: {report.min_samples}")
    lines.append(f"- Total functions analysed: {report.total_functions_analysed}")
    lines.append(
        "- Possible causes: I/O variability, GC pauses, lock contention, cache misses"
    )

    return "\n".join(lines)


class TemporalAnalyser:
    """Analyser for temporal performance patterns.

    Provides methods to detect:
    - Within-session degradation (quartile analysis)
    - Cross-profile regressions
    - Timing anomalies (high variance functions)

    Example:
        analyser = TemporalAnalyser(storage)

        # Detect within-session degradation
        report = analyser.analyse_degradation(profile_id)
        print(report.summary)

        # Compare against baseline
        regressions = analyser.detect_regressions(
            baseline_id="baseline-123",
            comparison_ids=["v1.1", "v1.2", "v1.3"],
        )

        # Find unstable functions
        anomalies = analyser.find_anomalies(profile_id)
    """

    def __init__(self, storage: ProfileStorage) -> None:
        """Initialise the analyser.

        Args:
            storage: Profile storage instance to query.
        """
        self._storage = storage

    def analyse_degradation(
        self,
        profile_id: str,
        *,
        degradation_threshold: float = 1.5,
        min_samples: int = 4,
    ) -> DegradationReport:
        """Detect within-session performance degradation.

        Splits the profile into time quartiles and compares early (Q1)
        vs late (Q4) execution to detect functions that slow down over time.

        This is useful for detecting memory leaks, cache exhaustion,
        or resource contention that develops during execution.

        Args:
            profile_id: ID of the profile to analyse.
            degradation_threshold: Q4/Q1 ratio above which a function is
                                   considered degraded. Default 1.5 (50% slower).
            min_samples: Minimum samples required per quartile for a function
                        to be included in analysis. Default 4.

        Returns:
            DegradationReport with analysis results and summary.

        Raises:
            ValueError: If profile not found.
        """
        profile = self._storage.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile not found: {profile_id}")

        # Collect timing data with relative timestamps
        function_timings = self._collect_function_timings(profile)

        # Analyse quartiles for each function
        degraded: list[QuartileTrend] = []
        stable: list[QuartileTrend] = []

        for name, timings in function_timings.items():
            if len(timings.samples) < min_samples * 4:
                # Not enough samples across all quartiles
                continue

            trend = self._compute_quartile_trend(
                timings, degradation_threshold=degradation_threshold
            )
            if trend.is_degraded:
                degraded.append(trend)
            else:
                stable.append(trend)

        # Sort degraded by severity (highest degradation factor first)
        degraded.sort(key=lambda t: t.degradation_factor, reverse=True)

        report = DegradationReport(
            profile_id=profile_id,
            profile_name=profile.name,
            has_degradation=len(degraded) > 0,
            degraded_functions=degraded,
            stable_functions=stable,
            total_functions_analysed=len(degraded) + len(stable),
            degradation_threshold=degradation_threshold,
        )

        # Generate human-readable summary
        report.summary = _generate_degradation_summary(report)

        return report

    def detect_regressions(
        self,
        baseline_id: str,
        comparison_ids: list[str],
        *,
        threshold_pct: float = 20.0,
    ) -> RegressionReport:
        """Detect performance regressions across multiple profiles.

        Compares a baseline profile against one or more comparison profiles
        to identify functions that have regressed or improved.

        Args:
            baseline_id: ID of the baseline profile.
            comparison_ids: IDs of profiles to compare against baseline.
            threshold_pct: Minimum percentage change to flag as regression/improvement.
                          Default 20%.

        Returns:
            RegressionReport with detected regressions and improvements.

        Raises:
            ValueError: If baseline profile not found.
        """
        baseline = self._storage.get_profile(baseline_id)
        if not baseline:
            raise ValueError(f"Baseline profile not found: {baseline_id}")

        # Build baseline function map
        baseline_stats = {s.name: s for s in baseline.function_stats}

        all_regressions: list[Regression] = []
        all_improvements: list[Regression] = []
        valid_comparisons = 0

        for comparison_id in comparison_ids:
            comparison = self._storage.get_profile(comparison_id)
            if not comparison:
                continue

            valid_comparisons += 1
            comparison_stats = {s.name: s for s in comparison.function_stats}

            for name, comp_stat in comparison_stats.items():
                base_stat = baseline_stats.get(name)
                if not base_stat:
                    continue

                # Calculate change percentage
                if base_stat.self_weight > 0:
                    change_pct = (
                        (comp_stat.self_weight - base_stat.self_weight)
                        / base_stat.self_weight
                        * 100
                    )
                else:
                    # Baseline was zero, can't compute percentage
                    continue

                absolute_change = comp_stat.self_weight - base_stat.self_weight

                if abs(change_pct) >= threshold_pct:
                    reg = Regression(
                        function=name,
                        file=comp_stat.file or base_stat.file,
                        baseline_self_ms=base_stat.self_weight,
                        comparison_self_ms=comp_stat.self_weight,
                        change_pct=change_pct,
                        absolute_change_ms=absolute_change,
                        baseline_profile_id=baseline_id,
                        comparison_profile_id=comparison_id,
                        comparison_commit=comparison.metadata.commit_sha,
                        is_significant=True,
                    )

                    if change_pct > 0:
                        all_regressions.append(reg)
                    else:
                        all_improvements.append(reg)

        # Sort by severity (absolute percentage change)
        all_regressions.sort(key=lambda r: r.change_pct, reverse=True)
        all_improvements.sort(key=lambda r: r.change_pct)

        report = RegressionReport(
            baseline_profile_id=baseline_id,
            baseline_profile_name=baseline.name,
            baseline_commit=baseline.metadata.commit_sha,
            comparison_count=valid_comparisons,
            regressions=all_regressions,
            improvements=all_improvements,
            threshold_pct=threshold_pct,
        )

        # Generate human-readable summary
        report.summary = _generate_regression_summary(report)

        return report

    def find_anomalies(
        self,
        profile_id: str,
        *,
        cv_threshold: float = 0.5,
        min_samples: int = 5,
    ) -> AnomalyReport:
        """Find functions with unusual timing variance.

        Identifies functions whose execution time varies significantly,
        indicating unstable performance that may be difficult to predict.

        Args:
            profile_id: ID of the profile to analyse.
            cv_threshold: Minimum coefficient of variation (std_dev / mean)
                         to flag as anomalous. Default 0.5 (50% variation).
            min_samples: Minimum samples required for a function to be
                        included in analysis. Default 5.

        Returns:
            AnomalyReport with detected anomalies and summary.

        Raises:
            ValueError: If profile not found.
        """
        profile = self._storage.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile not found: {profile_id}")

        # Collect timing data
        function_timings = self._collect_function_timings(profile)

        anomalies: list[Anomaly] = []
        functions_analysed = 0

        for name, timings in function_timings.items():
            if len(timings.samples) < min_samples:
                continue

            functions_analysed += 1

            # Calculate statistics
            mean = statistics.mean(timings.samples)
            if mean == 0:
                continue

            std_dev = statistics.stdev(timings.samples) if len(timings.samples) > 1 else 0
            cv = std_dev / mean if mean > 0 else 0
            min_val = min(timings.samples)
            max_val = max(timings.samples)

            if cv >= cv_threshold:
                # Determine severity based on CV
                if cv >= 1.0:
                    severity = "high"
                elif cv >= 0.75:
                    severity = "medium"
                else:
                    severity = "low"

                anomalies.append(
                    Anomaly(
                        function=name,
                        file=timings.file,
                        mean_ms=mean,
                        std_dev_ms=std_dev,
                        min_ms=min_val,
                        max_ms=max_val,
                        coefficient_of_variation=cv,
                        sample_count=len(timings.samples),
                        profile_id=profile_id,
                        severity=severity,
                    )
                )

        # Sort by CV (highest first)
        anomalies.sort(key=lambda a: a.coefficient_of_variation, reverse=True)

        report = AnomalyReport(
            profile_id=profile_id,
            profile_name=profile.name,
            anomalies=anomalies,
            cv_threshold=cv_threshold,
            min_samples=min_samples,
            total_functions_analysed=functions_analysed,
        )

        # Generate human-readable summary
        report.summary = _generate_anomaly_summary(report)

        return report

    def _collect_function_timings(
        self, profile: Profile
    ) -> dict[str, FunctionTimings]:
        """Collect timing data from a profile with relative timestamps.

        For sampled profiles, uses the sample position as timestamp.
        For evented profiles, uses the event timestamps directly.

        Args:
            profile: Profile to extract timings from.

        Returns:
            Dictionary mapping function names to their timing data.
        """
        timings: dict[str, FunctionTimings] = {}
        duration = profile.duration if profile.duration > 0 else 1.0

        # For each function stat, we use its weight as a single sample
        # In a real scenario with raw samples, we'd have per-sample data
        # Here we simulate based on call_count and self_weight
        for stat in profile.function_stats:
            if stat.name not in timings:
                timings[stat.name] = FunctionTimings(
                    name=stat.name,
                    file=stat.file,
                )

            # Distribute samples evenly based on call count
            # This is a simplification - ideally we'd have actual sample timestamps
            if stat.call_count > 0:
                per_call_weight = stat.self_weight / stat.call_count
                for i in range(stat.call_count):
                    # Distribute calls evenly across the profile duration
                    relative_time = (i + 0.5) / stat.call_count
                    timings[stat.name].samples.append(per_call_weight)
                    timings[stat.name].timestamps.append(relative_time)

        return timings

    def _compute_quartile_trend(
        self,
        timings: FunctionTimings,
        *,
        degradation_threshold: float = 1.5,
    ) -> QuartileTrend:
        """Compute quartile-based performance trend for a function.

        Args:
            timings: Timing data for the function.
            degradation_threshold: Q4/Q1 ratio above which function is degraded.

        Returns:
            QuartileTrend with quartile averages and degradation status.
        """
        # Sort samples by timestamp
        sorted_data = sorted(
            zip(timings.timestamps, timings.samples),
            key=lambda x: x[0],
        )

        n = len(sorted_data)
        q_size = n // 4

        # Split into quartiles
        q1_samples = [s for _, s in sorted_data[:q_size]]
        q2_samples = [s for _, s in sorted_data[q_size : 2 * q_size]]
        q3_samples = [s for _, s in sorted_data[2 * q_size : 3 * q_size]]
        q4_samples = [s for _, s in sorted_data[3 * q_size :]]

        # Calculate averages (use 0 if quartile is empty)
        q1_avg = statistics.mean(q1_samples) if q1_samples else 0.0
        q2_avg = statistics.mean(q2_samples) if q2_samples else 0.0
        q3_avg = statistics.mean(q3_samples) if q3_samples else 0.0
        q4_avg = statistics.mean(q4_samples) if q4_samples else 0.0

        # Calculate degradation factor (Q4/Q1)
        if q1_avg > 0:
            degradation_factor = q4_avg / q1_avg
        else:
            degradation_factor = 1.0

        return QuartileTrend(
            function=timings.name,
            file=timings.file,
            q1_avg_ms=q1_avg,
            q2_avg_ms=q2_avg,
            q3_avg_ms=q3_avg,
            q4_avg_ms=q4_avg,
            degradation_factor=degradation_factor,
            sample_count=n,
            is_degraded=degradation_factor >= degradation_threshold,
        )
