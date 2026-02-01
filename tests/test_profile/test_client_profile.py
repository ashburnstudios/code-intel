"""Tests for profile functionality in CodeIntelClient."""

from pathlib import Path

import pytest

from code_intel.client import CodeIntelClient
from code_intel.graph.schema import GraphNode, Location, NodeKind
from code_intel.profile.schema import ProfileMetadata


@pytest.fixture
def fixtures_path() -> Path:
    """Return path to profile test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sampled_profile_path(fixtures_path: Path) -> Path:
    """Return path to simple sampled profile."""
    return fixtures_path / "simple_sampled.speedscope.json"


@pytest.fixture
def multi_profile_path(fixtures_path: Path) -> Path:
    """Return path to multi-profile file."""
    return fixtures_path / "multi_profile.speedscope.json"


@pytest.fixture
def client() -> CodeIntelClient:
    """Create an in-memory client for testing."""
    return CodeIntelClient()


class TestClientProfileIngestion:
    """Tests for profile ingestion via client."""

    def test_ingest_profile(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test ingesting a profile through the client."""
        result = client.ingest_profile(sampled_profile_path)

        assert result.profiles_ingested == 1
        assert result.total_frames == 4
        assert result.total_functions > 0
        assert len(result.errors) == 0

    def test_ingest_profile_with_metadata(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test ingesting a profile with custom metadata."""
        metadata = ProfileMetadata(
            commit_sha="abc123",
            scenario="performance-test",
            tags=["test"],
        )
        result = client.ingest_profile(
            sampled_profile_path,
            metadata=metadata,
        )

        assert result.profiles_ingested == 1

        # Verify metadata was saved
        profiles = client.list_profiles()
        assert len(profiles) == 1
        assert profiles[0].metadata.commit_sha == "abc123"

    def test_ingest_multi_profile(
        self, client: CodeIntelClient, multi_profile_path: Path
    ) -> None:
        """Test ingesting a file with multiple profiles."""
        result = client.ingest_profile(multi_profile_path)

        assert result.profiles_ingested == 2

    def test_ingest_nonexistent_file(self, client: CodeIntelClient) -> None:
        """Test ingesting a nonexistent file."""
        result = client.ingest_profile(Path("/nonexistent/profile.json"))

        assert result.profiles_ingested == 0
        assert len(result.errors) == 1


class TestClientProfileQueries:
    """Tests for profile query methods."""

    def test_get_profile(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test retrieving a profile by ID."""
        client.ingest_profile(sampled_profile_path)
        profiles = client.list_profiles()
        profile_id = profiles[0].id

        profile = client.get_profile(profile_id)
        assert profile is not None
        assert profile.id == profile_id

    def test_get_nonexistent_profile(self, client: CodeIntelClient) -> None:
        """Test retrieving a nonexistent profile returns None."""
        profile = client.get_profile("nonexistent-id")
        assert profile is None

    def test_list_profiles(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test listing profiles."""
        client.ingest_profile(sampled_profile_path)

        profiles = client.list_profiles()
        assert len(profiles) == 1

    def test_delete_profile(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test deleting a profile."""
        client.ingest_profile(sampled_profile_path)
        profiles = client.list_profiles()
        profile_id = profiles[0].id

        deleted = client.delete_profile(profile_id)
        assert deleted is True

        assert client.get_profile(profile_id) is None

    def test_top_functions(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test getting top functions."""
        client.ingest_profile(sampled_profile_path)
        profiles = client.list_profiles()
        profile_id = profiles[0].id

        top = client.top_functions(profile_id, limit=3)
        assert len(top) <= 3
        # Verify sorted by self weight (descending)
        if len(top) > 1:
            assert top[0].self_weight >= top[1].self_weight

    def test_top_functions_by_total(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test getting top functions by total time."""
        client.ingest_profile(sampled_profile_path)
        profiles = client.list_profiles()
        profile_id = profiles[0].id

        top = client.top_functions(profile_id, limit=3, by="total")
        assert len(top) <= 3
        # Verify sorted by total weight (descending)
        if len(top) > 1:
            assert top[0].total_weight >= top[1].total_weight


class TestClientProfileComparison:
    """Tests for profile comparison."""

    def test_compare_profiles(
        self, client: CodeIntelClient, multi_profile_path: Path
    ) -> None:
        """Test comparing two profiles."""
        client.ingest_profile(multi_profile_path)
        profiles = client.list_profiles()

        # Sort by name to get consistent ordering
        profiles.sort(key=lambda p: p.name)
        baseline_id = profiles[0].id  # "After Optimisation" alphabetically first
        after_id = profiles[1].id  # "Baseline"

        comparison = client.compare_profiles(baseline_id, after_id)
        assert comparison is not None
        assert comparison.before_profile_id == baseline_id
        assert comparison.after_profile_id == after_id

    def test_compare_nonexistent_profiles(self, client: CodeIntelClient) -> None:
        """Test comparing nonexistent profiles returns None."""
        comparison = client.compare_profiles("fake-1", "fake-2")
        assert comparison is None


class TestClientFunctionTrend:
    """Tests for function trend analysis."""

    def test_function_trend(
        self, client: CodeIntelClient, multi_profile_path: Path
    ) -> None:
        """Test getting function trend over time."""
        client.ingest_profile(multi_profile_path)

        # "slow_function" appears in both profiles
        trend = client.function_trend("slow_function", limit=5)
        assert len(trend) == 2

        # Each entry is (Profile, FunctionStats)
        for profile, stats in trend:
            assert profile is not None
            assert stats is not None
            assert stats.name == "slow_function"


class TestClientHotCallers:
    """Tests for hot callers analysis (code graph + profile integration)."""

    def test_hot_callers_without_profile(self, client: CodeIntelClient) -> None:
        """Test hot callers without profile data returns callers with None stats."""
        # Create some nodes in the graph
        repo_path = "/test/repo"
        client._storage.create_node(
            GraphNode(
                id="caller:10",
                name="caller_func",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="caller.py",
                    start_line=10,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
            ),
            repo_path,
        )
        client._storage.create_node(
            GraphNode(
                id="target:50",
                name="target_func",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="target.py",
                    start_line=50,
                    start_column=0,
                    end_line=60,
                    end_column=0,
                ),
            ),
            repo_path,
        )

        # Create call edge
        from code_intel.graph.schema import EdgeKind, GraphEdge

        client._storage.create_edge(
            GraphEdge(
                source_id="caller:10",
                target_id="target:50",
                kind=EdgeKind.CALLS,
            )
        )

        # Query hot callers
        results = client.hot_callers("target_func", repo_path)
        assert len(results) == 1
        caller, stats = results[0]
        assert caller.name == "caller_func"
        assert stats is None  # No profile data

    def test_hot_callers_with_profile(
        self, client: CodeIntelClient, sampled_profile_path: Path
    ) -> None:
        """Test hot callers with profile data."""
        repo_path = "/test/repo"

        # Create nodes
        client._storage.create_node(
            GraphNode(
                id="main:10",
                name="main",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="src/main.py",
                    start_line=10,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
            ),
            repo_path,
        )
        client._storage.create_node(
            GraphNode(
                id="process:25",
                name="process_data",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="src/process.py",
                    start_line=25,
                    start_column=0,
                    end_line=50,
                    end_column=0,
                ),
            ),
            repo_path,
        )

        # Create call edge: main -> process_data
        from code_intel.graph.schema import EdgeKind, GraphEdge

        client._storage.create_edge(
            GraphEdge(
                source_id="main:10",
                target_id="process:25",
                kind=EdgeKind.CALLS,
            )
        )

        # Ingest profile
        client.ingest_profile(sampled_profile_path, repo_path=repo_path)
        profiles = client.list_profiles()
        profile_id = profiles[0].id

        # Query hot callers
        results = client.hot_callers("process_data", repo_path, profile_id=profile_id)
        assert len(results) == 1
        caller, stats = results[0]
        assert caller.name == "main"
        # Should have profile data for "main"
        assert stats is not None
        assert stats.name == "main"
