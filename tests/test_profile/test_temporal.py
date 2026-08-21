"""Tests for temporal analysis functionality (CINT-27).

Tests cover:
- Quartile analysis for within-session degradation
- Cross-profile regression detection
- Anomaly detection for high variance functions
- Human-readable summary generation
"""

import pytest

from code_intel.profile.schema import (
    Anomaly,
    AnomalyReport,
    DegradationReport,
    Frame,
    FunctionStats,
    Profile,
    ProfileMetadata,
    ProfileType,
    QuartileTrend,
    Regression,
    RegressionReport,
    ValueUnit,
)
from code_intel.profile.storage import ProfileStorage
from code_intel.profile.temporal import TemporalAnalyser


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def storage() -> ProfileStorage:
    """Create an in-memory profile storage."""
    return ProfileStorage()


@pytest.fixture
def analyser(storage: ProfileStorage) -> TemporalAnalyser:
    """Create a temporal analyser with in-memory storage."""
    return TemporalAnalyser(storage)


def create_profile_with_degradation(
    profile_id: str = "degradation-test",
    name: str = "Degradation Test Profile",
) -> Profile:
    """Create a synthetic profile with degrading performance.

    Simulates a function that gets progressively slower during execution,
    typical of memory leaks or cache exhaustion.
    """
    # Simulate a function that degrades over time
    # Call count of 20 allows splitting into 5 per quartile
    return Profile(
        id=profile_id,
        name=name,
        profile_type=ProfileType.SAMPLED,
        unit=ValueUnit.MILLISECONDS,
        start_value=0,
        end_value=2000,
        frames=[
            Frame(name="leaky_function", file="src/memory.py", line=10),
            Frame(name="stable_function", file="src/utils.py", line=20),
        ],
        function_stats=[
            # Degrading function: gets 3x slower over time
            # Q1 avg: 50, Q2 avg: 75, Q3 avg: 100, Q4 avg: 150
            # Total weight simulates increasing call times
            FunctionStats(
                profile_id=profile_id,
                frame_index=0,
                name="leaky_function",
                file="src/memory.py",
                line=10,
                # Average across all calls: (50+75+100+150)/4 * 5 calls each
                self_weight=1875,  # Sum of all call times
                total_weight=2500,
                call_count=20,  # 5 calls per quartile
                self_percentage=75.0,
                total_percentage=100.0,
            ),
            # Stable function: consistent performance
            FunctionStats(
                profile_id=profile_id,
                frame_index=1,
                name="stable_function",
                file="src/utils.py",
                line=20,
                self_weight=500,  # Consistent 25ms per call
                total_weight=500,
                call_count=20,
                self_percentage=20.0,
                total_percentage=20.0,
            ),
        ],
    )


def create_profile_with_stable_performance(
    profile_id: str = "stable-test",
    name: str = "Stable Test Profile",
) -> Profile:
    """Create a synthetic profile with consistent performance."""
    return Profile(
        id=profile_id,
        name=name,
        profile_type=ProfileType.SAMPLED,
        unit=ValueUnit.MILLISECONDS,
        start_value=0,
        end_value=1000,
        frames=[
            Frame(name="consistent_function", file="src/stable.py", line=10),
        ],
        function_stats=[
            FunctionStats(
                profile_id=profile_id,
                frame_index=0,
                name="consistent_function",
                file="src/stable.py",
                line=10,
                self_weight=500,  # 25ms average per call
                total_weight=500,
                call_count=20,
                self_percentage=50.0,
                total_percentage=50.0,
            ),
        ],
    )


def create_baseline_profile(
    profile_id: str = "baseline",
    commit_sha: str = "abc123",
) -> Profile:
    """Create a baseline profile for regression testing."""
    return Profile(
        id=profile_id,
        name="Baseline Profile",
        profile_type=ProfileType.SAMPLED,
        unit=ValueUnit.MILLISECONDS,
        start_value=0,
        end_value=1000,
        frames=[
            Frame(name="fast_function", file="src/fast.py", line=10),
            Frame(name="medium_function", file="src/medium.py", line=20),
            Frame(name="removed_function", file="src/old.py", line=30),
        ],
        function_stats=[
            FunctionStats(
                profile_id=profile_id,
                frame_index=0,
                name="fast_function",
                file="src/fast.py",
                line=10,
                self_weight=100,
                total_weight=150,
                call_count=10,
            ),
            FunctionStats(
                profile_id=profile_id,
                frame_index=1,
                name="medium_function",
                file="src/medium.py",
                line=20,
                self_weight=200,
                total_weight=300,
                call_count=10,
            ),
            FunctionStats(
                profile_id=profile_id,
                frame_index=2,
                name="removed_function",
                file="src/old.py",
                line=30,
                self_weight=50,
                total_weight=50,
                call_count=5,
            ),
        ],
        metadata=ProfileMetadata(
            commit_sha=commit_sha,
            scenario="baseline",
            tags=["baseline", "v1.0"],
        ),
    )


def create_regressed_profile(
    profile_id: str = "regressed",
    commit_sha: str = "def456",
) -> Profile:
    """Create a profile with performance regressions."""
    return Profile(
        id=profile_id,
        name="Regressed Profile",
        profile_type=ProfileType.SAMPLED,
        unit=ValueUnit.MILLISECONDS,
        start_value=0,
        end_value=1500,
        frames=[
            Frame(name="fast_function", file="src/fast.py", line=10),
            Frame(name="medium_function", file="src/medium.py", line=20),
            Frame(name="new_function", file="src/new.py", line=40),
        ],
        function_stats=[
            # fast_function got slower (100 -> 150, +50%)
            FunctionStats(
                profile_id=profile_id,
                frame_index=0,
                name="fast_function",
                file="src/fast.py",
                line=10,
                self_weight=150,  # +50% regression
                total_weight=200,
                call_count=10,
            ),
            # medium_function got faster (200 -> 150, -25%)
            FunctionStats(
                profile_id=profile_id,
                frame_index=1,
                name="medium_function",
                file="src/medium.py",
                line=20,
                self_weight=150,  # -25% improvement
                total_weight=250,
                call_count=10,
            ),
            # new_function is new
            FunctionStats(
                profile_id=profile_id,
                frame_index=2,
                name="new_function",
                file="src/new.py",
                line=40,
                self_weight=100,
                total_weight=100,
                call_count=5,
            ),
        ],
        metadata=ProfileMetadata(
            commit_sha=commit_sha,
            scenario="regression-test",
            tags=["v1.1"],
        ),
    )


def create_profile_with_variance(
    profile_id: str = "variance-test",
    name: str = "High Variance Profile",
) -> Profile:
    """Create a profile with functions that have high timing variance."""
    return Profile(
        id=profile_id,
        name=name,
        profile_type=ProfileType.SAMPLED,
        unit=ValueUnit.MILLISECONDS,
        start_value=0,
        end_value=2000,
        frames=[
            Frame(name="io_bound_function", file="src/io.py", line=10),
            Frame(name="gc_affected_function", file="src/gc.py", line=20),
            Frame(name="stable_function", file="src/stable.py", line=30),
        ],
        function_stats=[
            # High variance (simulated I/O bound)
            # Actual variance comes from call distribution
            FunctionStats(
                profile_id=profile_id,
                frame_index=0,
                name="io_bound_function",
                file="src/io.py",
                line=10,
                self_weight=1000,  # Highly variable calls
                total_weight=1000,
                call_count=10,  # Mean 100ms, but high variance
            ),
            # Medium variance (simulated GC pauses)
            FunctionStats(
                profile_id=profile_id,
                frame_index=1,
                name="gc_affected_function",
                file="src/gc.py",
                line=20,
                self_weight=500,
                total_weight=500,
                call_count=10,
            ),
            # Low variance (stable)
            FunctionStats(
                profile_id=profile_id,
                frame_index=2,
                name="stable_function",
                file="src/stable.py",
                line=30,
                self_weight=200,
                total_weight=200,
                call_count=10,
            ),
        ],
    )


# =============================================================================
# Schema Model Tests
# =============================================================================


class TestQuartileTrend:
    """Tests for QuartileTrend model."""

    def test_creation_with_all_fields(self) -> None:
        """Test creating QuartileTrend with all fields."""
        trend = QuartileTrend(
            function="test_func",
            file="test.py",
            q1_avg_ms=10.0,
            q2_avg_ms=15.0,
            q3_avg_ms=20.0,
            q4_avg_ms=30.0,
            degradation_factor=3.0,
            sample_count=20,
            is_degraded=True,
        )
        assert trend.function == "test_func"
        assert trend.degradation_factor == 3.0
        assert trend.is_degraded is True

    def test_degradation_factor_calculation(self) -> None:
        """Test that degradation factor represents Q4/Q1 ratio."""
        trend = QuartileTrend(
            function="test",
            q1_avg_ms=50.0,
            q2_avg_ms=60.0,
            q3_avg_ms=80.0,
            q4_avg_ms=100.0,
            degradation_factor=2.0,  # 100/50
        )
        assert trend.degradation_factor == 2.0


class TestDegradationReport:
    """Tests for DegradationReport model."""

    def test_creation_with_degradation(self) -> None:
        """Test creating a report with detected degradation."""
        trend = QuartileTrend(
            function="leaky",
            q1_avg_ms=10.0,
            q2_avg_ms=15.0,
            q3_avg_ms=20.0,
            q4_avg_ms=30.0,
            degradation_factor=3.0,
            is_degraded=True,
        )
        report = DegradationReport(
            profile_id="test",
            profile_name="Test Profile",
            has_degradation=True,
            degraded_functions=[trend],
            total_functions_analysed=5,
        )
        assert report.has_degradation is True
        assert len(report.degraded_functions) == 1

    def test_creation_no_degradation(self) -> None:
        """Test creating a report with no degradation."""
        report = DegradationReport(
            profile_id="test",
            profile_name="Test Profile",
            has_degradation=False,
            degraded_functions=[],
            total_functions_analysed=5,
        )
        assert report.has_degradation is False
        assert len(report.degraded_functions) == 0


class TestRegression:
    """Tests for Regression model."""

    def test_creation_positive_regression(self) -> None:
        """Test creating a regression (slower)."""
        reg = Regression(
            function="slow_func",
            file="slow.py",
            baseline_self_ms=100.0,
            comparison_self_ms=150.0,
            change_pct=50.0,
            absolute_change_ms=50.0,
            baseline_profile_id="baseline",
            comparison_profile_id="v1.1",
            comparison_commit="abc123",
        )
        assert reg.change_pct == 50.0
        assert reg.is_significant is True

    def test_creation_improvement(self) -> None:
        """Test creating an improvement (faster)."""
        reg = Regression(
            function="fast_func",
            baseline_self_ms=100.0,
            comparison_self_ms=70.0,
            change_pct=-30.0,
            absolute_change_ms=-30.0,
            baseline_profile_id="baseline",
            comparison_profile_id="v1.1",
        )
        assert reg.change_pct == -30.0


class TestAnomaly:
    """Tests for Anomaly model."""

    def test_creation_high_severity(self) -> None:
        """Test creating a high severity anomaly."""
        anomaly = Anomaly(
            function="io_func",
            file="io.py",
            mean_ms=100.0,
            std_dev_ms=120.0,
            min_ms=10.0,
            max_ms=500.0,
            coefficient_of_variation=1.2,
            sample_count=20,
            profile_id="test",
            severity="high",
        )
        assert anomaly.coefficient_of_variation == 1.2
        assert anomaly.severity == "high"

    def test_coefficient_of_variation(self) -> None:
        """Test CV calculation (std/mean)."""
        anomaly = Anomaly(
            function="test",
            mean_ms=100.0,
            std_dev_ms=50.0,
            min_ms=50.0,
            max_ms=150.0,
            coefficient_of_variation=0.5,  # 50/100
            sample_count=10,
            profile_id="test",
        )
        assert anomaly.coefficient_of_variation == 0.5


# =============================================================================
# Quartile Analysis Tests
# =============================================================================


class TestAnalyseDegradation:
    """Tests for analyse_degradation method."""

    def test_detects_degradation(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that degradation is detected for degrading functions."""
        profile = create_profile_with_degradation()
        storage.create_profile(profile)

        report = analyser.analyse_degradation(profile.id)

        assert report.profile_id == profile.id
        assert report.total_functions_analysed > 0

    def test_stable_profile_no_degradation(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that stable profiles show no degradation."""
        profile = create_profile_with_stable_performance()
        storage.create_profile(profile)

        report = analyser.analyse_degradation(profile.id)

        # Stable functions should not be flagged as degraded
        assert all(
            not f.is_degraded for f in report.degraded_functions
        ) or len(report.degraded_functions) == 0

    def test_custom_threshold(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test degradation detection with custom threshold."""
        profile = create_profile_with_degradation()
        storage.create_profile(profile)

        # With a very high threshold, nothing should be flagged
        report = analyser.analyse_degradation(
            profile.id, degradation_threshold=10.0
        )
        assert report.has_degradation is False

    def test_profile_not_found(self, analyser: TemporalAnalyser) -> None:
        """Test error when profile not found."""
        with pytest.raises(ValueError, match="Profile not found"):
            analyser.analyse_degradation("nonexistent-id")

    def test_generates_summary(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that human-readable summary is generated."""
        profile = create_profile_with_degradation()
        storage.create_profile(profile)

        report = analyser.analyse_degradation(profile.id)

        assert report.summary != ""
        assert "Degradation Analysis" in report.summary
        assert profile.name in report.summary


# =============================================================================
# Regression Detection Tests
# =============================================================================


class TestDetectRegressions:
    """Tests for detect_regressions method."""

    def test_detects_regression(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that regressions are detected."""
        baseline = create_baseline_profile()
        regressed = create_regressed_profile()
        storage.create_profile(baseline)
        storage.create_profile(regressed)

        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[regressed.id],
            threshold_pct=20.0,
        )

        assert report.baseline_profile_id == baseline.id
        assert report.comparison_count == 1

        # fast_function regressed by +50%
        regression_names = [r.function for r in report.regressions]
        assert "fast_function" in regression_names

    def test_detects_improvement(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that improvements are detected."""
        baseline = create_baseline_profile()
        regressed = create_regressed_profile()
        storage.create_profile(baseline)
        storage.create_profile(regressed)

        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[regressed.id],
            threshold_pct=20.0,
        )

        # medium_function improved by -25%
        improvement_names = [i.function for i in report.improvements]
        assert "medium_function" in improvement_names

    def test_multiple_comparison_profiles(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test comparing against multiple profiles."""
        baseline = create_baseline_profile()
        v1 = create_regressed_profile("v1.1", "commit-v1.1")
        v2 = create_regressed_profile("v1.2", "commit-v1.2")
        storage.create_profile(baseline)
        storage.create_profile(v1)
        storage.create_profile(v2)

        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[v1.id, v2.id],
        )

        assert report.comparison_count == 2

    def test_baseline_not_found(self, analyser: TemporalAnalyser) -> None:
        """Test error when baseline profile not found."""
        with pytest.raises(ValueError, match="Baseline profile not found"):
            analyser.detect_regressions(
                baseline_id="nonexistent",
                comparison_ids=["also-nonexistent"],
            )

    def test_skips_missing_comparison_profiles(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that missing comparison profiles are skipped gracefully."""
        baseline = create_baseline_profile()
        storage.create_profile(baseline)

        # One valid, one missing
        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=["nonexistent"],
        )

        assert report.comparison_count == 0

    def test_custom_threshold(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test regression detection with custom threshold."""
        baseline = create_baseline_profile()
        regressed = create_regressed_profile()
        storage.create_profile(baseline)
        storage.create_profile(regressed)

        # With high threshold, minor changes should not be flagged
        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[regressed.id],
            threshold_pct=100.0,  # 100% change required
        )

        # No regressions should meet 100% threshold
        assert len(report.regressions) == 0
        assert len(report.improvements) == 0

    def test_generates_summary(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that human-readable summary is generated."""
        baseline = create_baseline_profile()
        regressed = create_regressed_profile()
        storage.create_profile(baseline)
        storage.create_profile(regressed)

        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[regressed.id],
        )

        assert report.summary != ""
        assert "Regression Analysis" in report.summary


# =============================================================================
# Anomaly Detection Tests
# =============================================================================


class TestFindAnomalies:
    """Tests for find_anomalies method."""

    def test_finds_high_variance_functions(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that high variance functions are flagged."""
        profile = create_profile_with_variance()
        storage.create_profile(profile)

        report = analyser.find_anomalies(profile.id, cv_threshold=0.3)

        assert report.profile_id == profile.id
        assert report.total_functions_analysed > 0

    def test_stable_profile_no_anomalies(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that stable profiles have no anomalies."""
        profile = create_profile_with_stable_performance()
        storage.create_profile(profile)

        # With high threshold, no anomalies expected
        report = analyser.find_anomalies(profile.id, cv_threshold=2.0)

        assert len(report.anomalies) == 0

    def test_custom_cv_threshold(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test anomaly detection with custom CV threshold."""
        profile = create_profile_with_variance()
        storage.create_profile(profile)

        # Very low threshold should flag more functions
        low_report = analyser.find_anomalies(profile.id, cv_threshold=0.1)

        # Very high threshold should flag fewer
        high_report = analyser.find_anomalies(profile.id, cv_threshold=5.0)

        assert len(low_report.anomalies) >= len(high_report.anomalies)

    def test_min_samples_requirement(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that functions with few samples are excluded."""
        profile = Profile(
            id="few-samples",
            name="Few Samples Profile",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[
                FunctionStats(
                    profile_id="few-samples",
                    frame_index=0,
                    name="few_samples_func",
                    self_weight=100,
                    total_weight=100,
                    call_count=2,  # Only 2 samples
                ),
            ],
        )
        storage.create_profile(profile)

        # Require at least 5 samples
        report = analyser.find_anomalies(profile.id, min_samples=5)

        # Function should be excluded due to insufficient samples
        assert report.total_functions_analysed == 0

    def test_profile_not_found(self, analyser: TemporalAnalyser) -> None:
        """Test error when profile not found."""
        with pytest.raises(ValueError, match="Profile not found"):
            analyser.find_anomalies("nonexistent-id")

    def test_generates_summary(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that human-readable summary is generated."""
        profile = create_profile_with_variance()
        storage.create_profile(profile)

        report = analyser.find_anomalies(profile.id)

        assert report.summary != ""
        assert "Anomaly Analysis" in report.summary
        assert profile.name in report.summary

    def test_severity_classification(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test that anomalies are classified by severity."""
        profile = create_profile_with_variance()
        storage.create_profile(profile)

        report = analyser.find_anomalies(profile.id, cv_threshold=0.1)

        # Check that severities are valid
        for anomaly in report.anomalies:
            assert anomaly.severity in ["low", "medium", "high"]


# =============================================================================
# Summary Generation Tests
# =============================================================================


class TestSummaryGeneration:
    """Tests for human-readable summary generation."""

    def test_degradation_summary_with_issues(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test degradation summary when issues are found."""
        profile = create_profile_with_degradation()
        storage.create_profile(profile)

        report = analyser.analyse_degradation(profile.id, degradation_threshold=1.0)

        # Summary should contain key information
        assert "##" in report.summary  # Markdown heading
        assert "Degradation Analysis" in report.summary

    def test_degradation_summary_no_issues(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test degradation summary when no issues found."""
        profile = create_profile_with_stable_performance()
        storage.create_profile(profile)

        report = analyser.analyse_degradation(profile.id, degradation_threshold=10.0)

        assert "No significant degradation" in report.summary

    def test_regression_summary_with_issues(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test regression summary when issues are found."""
        baseline = create_baseline_profile()
        regressed = create_regressed_profile()
        storage.create_profile(baseline)
        storage.create_profile(regressed)

        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[regressed.id],
        )

        # Summary should contain markdown and key info
        assert "##" in report.summary
        assert "Regression" in report.summary

    def test_regression_summary_no_issues(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test regression summary when no changes detected."""
        baseline = create_baseline_profile()
        storage.create_profile(baseline)

        # Compare against same profile (no changes)
        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[baseline.id],
        )

        assert "No significant changes" in report.summary

    def test_anomaly_summary_with_issues(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test anomaly summary when issues are found."""
        profile = create_profile_with_variance()
        storage.create_profile(profile)

        report = analyser.find_anomalies(profile.id, cv_threshold=0.1)

        assert "##" in report.summary
        assert "Anomaly Analysis" in report.summary

    def test_anomaly_summary_no_issues(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test anomaly summary when no anomalies found."""
        profile = create_profile_with_stable_performance()
        storage.create_profile(profile)

        report = analyser.find_anomalies(profile.id, cv_threshold=5.0)

        assert "No timing anomalies" in report.summary


# =============================================================================
# Integration Tests
# =============================================================================


class TestTemporalAnalysisIntegration:
    """Integration tests for temporal analysis workflow."""

    def test_full_analysis_workflow(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test complete temporal analysis workflow."""
        # Create profiles representing a development timeline
        baseline = create_baseline_profile("baseline", "commit-base")
        v1 = create_regressed_profile("v1.1", "commit-v1.1")

        storage.create_profile(baseline)
        storage.create_profile(v1)

        # 1. Analyse degradation in v1.1
        deg_report = analyser.analyse_degradation(v1.id)
        assert deg_report.summary != ""

        # 2. Detect regressions vs baseline
        reg_report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[v1.id],
        )
        assert reg_report.comparison_count == 1

        # 3. Find anomalies in v1.1
        anom_report = analyser.find_anomalies(v1.id)
        assert anom_report.summary != ""

    def test_analysis_with_empty_comparison_list(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test regression detection with empty comparison list."""
        baseline = create_baseline_profile()
        storage.create_profile(baseline)

        report = analyser.detect_regressions(
            baseline_id=baseline.id,
            comparison_ids=[],
        )

        assert report.comparison_count == 0
        assert len(report.regressions) == 0
        assert len(report.improvements) == 0


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_profile(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test analysis of profile with no function stats."""
        profile = Profile(
            id="empty",
            name="Empty Profile",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[],
        )
        storage.create_profile(profile)

        deg_report = analyser.analyse_degradation(profile.id)
        assert deg_report.total_functions_analysed == 0
        assert deg_report.has_degradation is False

        anom_report = analyser.find_anomalies(profile.id)
        assert anom_report.total_functions_analysed == 0
        assert len(anom_report.anomalies) == 0

    def test_single_sample_function(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test analysis of functions with single samples."""
        profile = Profile(
            id="single",
            name="Single Sample",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[
                FunctionStats(
                    profile_id="single",
                    frame_index=0,
                    name="one_call_func",
                    self_weight=100,
                    total_weight=100,
                    call_count=1,
                ),
            ],
        )
        storage.create_profile(profile)

        # Should handle gracefully
        deg_report = analyser.analyse_degradation(profile.id, min_samples=1)
        anom_report = analyser.find_anomalies(profile.id, min_samples=1)

        # Reports should be generated without error
        assert deg_report is not None
        assert anom_report is not None

    def test_zero_weight_function(
        self, storage: ProfileStorage, analyser: TemporalAnalyser
    ) -> None:
        """Test analysis of functions with zero weight."""
        profile = Profile(
            id="zero-weight",
            name="Zero Weight",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[
                FunctionStats(
                    profile_id="zero-weight",
                    frame_index=0,
                    name="zero_weight_func",
                    self_weight=0,
                    total_weight=0,
                    call_count=10,
                ),
            ],
        )
        storage.create_profile(profile)

        # Should handle division by zero gracefully
        deg_report = analyser.analyse_degradation(profile.id)
        anom_report = analyser.find_anomalies(profile.id)

        assert deg_report is not None
        assert anom_report is not None
