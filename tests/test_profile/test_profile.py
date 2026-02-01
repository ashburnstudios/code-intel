"""Tests for profile analysis functionality."""

from pathlib import Path

import pytest

from code_intel.profile.schema import (
    Frame,
    FrameSymbolMapping,
    FunctionStats,
    Profile,
    ProfileMetadata,
    ProfileType,
    ValueUnit,
)
from code_intel.profile.speedscope import SpeedscopeParser
from code_intel.profile.storage import ProfileStorage


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fixtures_path() -> Path:
    """Return path to profile test fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sampled_profile_path(fixtures_path: Path) -> Path:
    """Return path to simple sampled profile."""
    return fixtures_path / "simple_sampled.speedscope.json"


@pytest.fixture
def evented_profile_path(fixtures_path: Path) -> Path:
    """Return path to simple evented profile."""
    return fixtures_path / "simple_evented.speedscope.json"


@pytest.fixture
def multi_profile_path(fixtures_path: Path) -> Path:
    """Return path to multi-profile file."""
    return fixtures_path / "multi_profile.speedscope.json"


@pytest.fixture
def parser() -> SpeedscopeParser:
    """Create a speedscope parser."""
    return SpeedscopeParser()


@pytest.fixture
def storage() -> ProfileStorage:
    """Create an in-memory profile storage."""
    return ProfileStorage()


@pytest.fixture
def sample_profile() -> Profile:
    """Create a sample profile for testing."""
    return Profile(
        id="test-profile-123",
        name="Test Profile",
        profile_type=ProfileType.SAMPLED,
        unit=ValueUnit.MILLISECONDS,
        start_value=0,
        end_value=1000,
        frames=[
            Frame(name="main", file="main.py", line=10),
            Frame(name="helper", file="utils.py", line=20),
        ],
        function_stats=[
            FunctionStats(
                profile_id="test-profile-123",
                frame_index=0,
                name="main",
                file="main.py",
                line=10,
                self_weight=300,
                total_weight=1000,
                call_count=1,
                self_percentage=30.0,
                total_percentage=100.0,
            ),
            FunctionStats(
                profile_id="test-profile-123",
                frame_index=1,
                name="helper",
                file="utils.py",
                line=20,
                self_weight=700,
                total_weight=700,
                call_count=5,
                self_percentage=70.0,
                total_percentage=70.0,
            ),
        ],
        metadata=ProfileMetadata(
            commit_sha="abc123",
            scenario="unit-test",
            tags=["test", "sample"],
        ),
    )


# =============================================================================
# Schema Tests
# =============================================================================


class TestFrame:
    """Tests for Frame schema."""

    def test_to_qualified_name_simple(self) -> None:
        """Test qualified name for simple function."""
        frame = Frame(name="process_data")
        assert frame.to_qualified_name() == "process_data"

    def test_to_qualified_name_with_args(self) -> None:
        """Test qualified name strips arguments."""
        frame = Frame(name="MyClass.method(int, string)")
        assert frame.to_qualified_name() == "MyClass.method"

    def test_to_qualified_name_dotted(self) -> None:
        """Test qualified name preserves dots."""
        frame = Frame(name="namespace.Class.Method")
        assert frame.to_qualified_name() == "namespace.Class.Method"


class TestFunctionStats:
    """Tests for FunctionStats schema."""

    def test_creation(self) -> None:
        """Test creating FunctionStats with all fields."""
        stats = FunctionStats(
            profile_id="p1",
            frame_index=0,
            name="test_func",
            file="test.py",
            line=10,
            self_weight=100.0,
            total_weight=200.0,
            call_count=5,
            self_percentage=10.0,
            total_percentage=20.0,
            symbol_id="sym-123",
        )
        assert stats.name == "test_func"
        assert stats.self_weight == 100.0
        assert stats.symbol_id == "sym-123"


class TestProfile:
    """Tests for Profile schema."""

    def test_duration_calculation(self, sample_profile: Profile) -> None:
        """Test profile duration calculation."""
        assert sample_profile.duration == 1000

    def test_get_hotspots_by_self(self, sample_profile: Profile) -> None:
        """Test getting hotspots sorted by self time."""
        hotspots = sample_profile.get_hotspots(limit=10, by="self")
        assert len(hotspots) == 2
        assert hotspots[0].name == "helper"  # Higher self weight
        assert hotspots[1].name == "main"

    def test_get_hotspots_by_total(self, sample_profile: Profile) -> None:
        """Test getting hotspots sorted by total time."""
        hotspots = sample_profile.get_hotspots(limit=10, by="total")
        assert len(hotspots) == 2
        assert hotspots[0].name == "main"  # Higher total weight

    def test_get_hotspots_limited(self, sample_profile: Profile) -> None:
        """Test hotspots with limit."""
        hotspots = sample_profile.get_hotspots(limit=1)
        assert len(hotspots) == 1


# =============================================================================
# Parser Tests
# =============================================================================


class TestSpeedscopeParser:
    """Tests for speedscope parser."""

    def test_parse_sampled_profile(
        self, parser: SpeedscopeParser, sampled_profile_path: Path
    ) -> None:
        """Test parsing a sampled profile."""
        profiles = parser.parse_file(sampled_profile_path)

        assert len(profiles) == 1
        profile = profiles[0]

        assert profile.profile_type == ProfileType.SAMPLED
        assert profile.unit == ValueUnit.MILLISECONDS
        assert len(profile.frames) == 4
        assert profile.start_value == 0
        assert profile.end_value == 1000

        # Check frame names
        frame_names = [f.name for f in profile.frames]
        assert "main" in frame_names
        assert "process_data" in frame_names
        assert "calculate" in frame_names
        assert "helper" in frame_names

    def test_parse_sampled_stats(
        self, parser: SpeedscopeParser, sampled_profile_path: Path
    ) -> None:
        """Test that sampled profile computes correct stats."""
        profiles = parser.parse_file(sampled_profile_path)
        profile = profiles[0]

        # Find stats by name
        stats_by_name = {s.name: s for s in profile.function_stats}

        # calculate: appears at top of 2 samples (200 + 300 = 500 self weight)
        assert stats_by_name["calculate"].self_weight == 500
        assert stats_by_name["calculate"].call_count == 2

        # helper: appears at top of 1 sample (150 self weight)
        assert stats_by_name["helper"].self_weight == 150
        assert stats_by_name["helper"].call_count == 1

        # process_data: appears at top of 1 sample (200 self weight)
        assert stats_by_name["process_data"].self_weight == 200
        assert stats_by_name["process_data"].call_count == 1

        # main: appears at top of 1 sample (150 self weight)
        assert stats_by_name["main"].self_weight == 150
        assert stats_by_name["main"].call_count == 1

    def test_parse_evented_profile(
        self, parser: SpeedscopeParser, evented_profile_path: Path
    ) -> None:
        """Test parsing an evented profile."""
        profiles = parser.parse_file(evented_profile_path)

        assert len(profiles) == 1
        profile = profiles[0]

        assert profile.profile_type == ProfileType.EVENTED
        assert profile.unit == ValueUnit.MILLISECONDS
        assert len(profile.frames) == 3
        assert profile.duration == 500

    def test_parse_evented_stats(
        self, parser: SpeedscopeParser, evented_profile_path: Path
    ) -> None:
        """Test that evented profile computes correct stats."""
        profiles = parser.parse_file(evented_profile_path)
        profile = profiles[0]

        stats_by_name = {s.name: s for s in profile.function_stats}

        # calculate: open at 100, close at 300 = 200ms total
        assert stats_by_name["calculate"].total_weight == 200
        assert stats_by_name["calculate"].call_count == 1

        # process_data: open at 50, close at 400 = 350ms total
        assert stats_by_name["process_data"].total_weight == 350
        assert stats_by_name["process_data"].call_count == 1

        # main: open at 0, close at 500 = 500ms total
        assert stats_by_name["main"].total_weight == 500
        assert stats_by_name["main"].call_count == 1

    def test_parse_multi_profile(
        self, parser: SpeedscopeParser, multi_profile_path: Path
    ) -> None:
        """Test parsing a file with multiple profiles."""
        profiles = parser.parse_file(multi_profile_path)

        assert len(profiles) == 2
        assert "Baseline" in profiles[0].name
        assert "Optimisation" in profiles[1].name

    def test_parse_with_metadata(
        self, parser: SpeedscopeParser, sampled_profile_path: Path
    ) -> None:
        """Test parsing with custom metadata."""
        metadata = ProfileMetadata(
            commit_sha="test-sha",
            scenario="performance-test",
            tags=["automated"],
        )
        profiles = parser.parse_file(
            sampled_profile_path,
            repo_path="/test/repo",
            metadata=metadata,
        )

        profile = profiles[0]
        assert profile.repo_path == "/test/repo"
        assert profile.metadata.commit_sha == "test-sha"
        assert profile.metadata.scenario == "performance-test"
        assert "automated" in profile.metadata.tags

    def test_parse_nonexistent_file(self, parser: SpeedscopeParser) -> None:
        """Test parsing a nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            parser.parse_file(Path("/nonexistent/profile.json"))

    def test_parse_invalid_format(self, parser: SpeedscopeParser, tmp_path: Path) -> None:
        """Test parsing invalid JSON raises error."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text('{"not": "speedscope"}')

        with pytest.raises(ValueError, match="Invalid speedscope format"):
            parser.parse_file(invalid_file)


# =============================================================================
# Storage Tests
# =============================================================================


class TestProfileStorage:
    """Tests for profile storage."""

    def test_create_and_get_profile(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test creating and retrieving a profile."""
        storage.create_profile(sample_profile)

        retrieved = storage.get_profile(sample_profile.id)
        assert retrieved is not None
        assert retrieved.id == sample_profile.id
        assert retrieved.name == sample_profile.name
        assert retrieved.profile_type == sample_profile.profile_type
        assert len(retrieved.frames) == len(sample_profile.frames)
        assert len(retrieved.function_stats) == len(sample_profile.function_stats)

    def test_delete_profile(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test deleting a profile."""
        storage.create_profile(sample_profile)
        assert storage.get_profile(sample_profile.id) is not None

        deleted = storage.delete_profile(sample_profile.id)
        assert deleted is True
        assert storage.get_profile(sample_profile.id) is None

    def test_delete_nonexistent_profile(self, storage: ProfileStorage) -> None:
        """Test deleting a nonexistent profile returns False."""
        deleted = storage.delete_profile("nonexistent-id")
        assert deleted is False

    def test_list_profiles(self, storage: ProfileStorage) -> None:
        """Test listing profiles."""
        # Create multiple profiles
        for i in range(3):
            profile = Profile(
                id=f"profile-{i}",
                name=f"Profile {i}",
                profile_type=ProfileType.SAMPLED,
                unit=ValueUnit.MILLISECONDS,
                repo_path="/test/repo",
            )
            storage.create_profile(profile)

        profiles = storage.list_profiles()
        assert len(profiles) == 3

    def test_list_profiles_by_repo(self, storage: ProfileStorage) -> None:
        """Test listing profiles filtered by repository."""
        storage.create_profile(
            Profile(
                id="p1",
                name="Repo A Profile",
                profile_type=ProfileType.SAMPLED,
                unit=ValueUnit.MILLISECONDS,
                repo_path="/repo/a",
            )
        )
        storage.create_profile(
            Profile(
                id="p2",
                name="Repo B Profile",
                profile_type=ProfileType.SAMPLED,
                unit=ValueUnit.MILLISECONDS,
                repo_path="/repo/b",
            )
        )

        repo_a_profiles = storage.list_profiles("/repo/a")
        assert len(repo_a_profiles) == 1
        assert repo_a_profiles[0].id == "p1"

    def test_list_profiles_with_limit(self, storage: ProfileStorage) -> None:
        """Test listing profiles with limit and offset."""
        for i in range(5):
            storage.create_profile(
                Profile(
                    id=f"p{i}",
                    name=f"Profile {i}",
                    profile_type=ProfileType.SAMPLED,
                    unit=ValueUnit.MILLISECONDS,
                )
            )

        profiles = storage.list_profiles(limit=2)
        assert len(profiles) == 2

    def test_get_top_functions(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test getting top functions by self time."""
        storage.create_profile(sample_profile)

        top = storage.get_top_functions(sample_profile.id, limit=10, by="self")
        assert len(top) == 2
        assert top[0].name == "helper"  # Higher self weight

    def test_get_top_functions_by_total(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test getting top functions by total time."""
        storage.create_profile(sample_profile)

        top = storage.get_top_functions(sample_profile.id, limit=10, by="total")
        assert len(top) == 2
        assert top[0].name == "main"  # Higher total weight

    def test_compare_profiles(self, storage: ProfileStorage) -> None:
        """Test comparing two profiles."""
        # Create "before" profile
        before = Profile(
            id="before",
            name="Before",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            start_value=0,
            end_value=100,
            function_stats=[
                FunctionStats(
                    profile_id="before",
                    frame_index=0,
                    name="slow_func",
                    self_weight=50,
                    total_weight=80,
                    call_count=10,
                ),
                FunctionStats(
                    profile_id="before",
                    frame_index=1,
                    name="fast_func",
                    self_weight=10,
                    total_weight=20,
                    call_count=5,
                ),
            ],
        )
        storage.create_profile(before)

        # Create "after" profile with regression
        after = Profile(
            id="after",
            name="After",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            start_value=0,
            end_value=150,
            function_stats=[
                FunctionStats(
                    profile_id="after",
                    frame_index=0,
                    name="slow_func",
                    self_weight=100,  # Got slower
                    total_weight=130,
                    call_count=15,
                ),
                FunctionStats(
                    profile_id="after",
                    frame_index=1,
                    name="fast_func",
                    self_weight=5,  # Got faster
                    total_weight=10,
                    call_count=3,
                ),
            ],
        )
        storage.create_profile(after)

        comparison = storage.compare_profiles("before", "after")
        assert comparison is not None
        assert comparison.duration_delta == 50
        assert len(comparison.regressions) == 1
        assert comparison.regressions[0].name == "slow_func"
        assert len(comparison.improvements) == 1
        assert comparison.improvements[0].name == "fast_func"

    def test_function_trend(self, storage: ProfileStorage) -> None:
        """Test getting function trend over time."""
        # Create profiles with the same function at different times
        for i in range(3):
            profile = Profile(
                id=f"trend-{i}",
                name=f"Trend Profile {i}",
                profile_type=ProfileType.SAMPLED,
                unit=ValueUnit.MILLISECONDS,
                function_stats=[
                    FunctionStats(
                        profile_id=f"trend-{i}",
                        frame_index=0,
                        name="tracked_func",
                        self_weight=100 + (i * 10),  # Getting slower
                        total_weight=200 + (i * 10),
                        call_count=5,
                    )
                ],
            )
            storage.create_profile(profile)

        trend = storage.get_function_trend("tracked_func", limit=3)
        assert len(trend) == 3
        # Most recent first
        assert trend[0][1].self_weight == 120
        assert trend[2][1].self_weight == 100

    def test_update_symbol_correlations(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test updating symbol correlations."""
        storage.create_profile(sample_profile)

        # Update correlations
        correlations = {0: "node-main-123", 1: "node-helper-456"}
        count = storage.update_symbol_correlations(sample_profile.id, correlations)
        assert count == 2

        # Verify correlations were saved
        profile = storage.get_profile(sample_profile.id)
        assert profile is not None
        stats_by_idx = {s.frame_index: s for s in profile.function_stats}
        assert stats_by_idx[0].symbol_id == "node-main-123"
        assert stats_by_idx[1].symbol_id == "node-helper-456"

    def test_get_functions_by_symbol(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test getting profile data by symbol ID."""
        # Manually set a symbol ID
        sample_profile.function_stats[0].symbol_id = "symbol-123"
        storage.create_profile(sample_profile)

        # Update in database
        storage.update_symbol_correlations(sample_profile.id, {0: "symbol-123"})

        results = storage.get_functions_by_symbol("symbol-123")
        assert len(results) == 1
        assert results[0][1].name == "main"


# =============================================================================
# Frame Symbol Mapping Tests
# =============================================================================


class TestFrameSymbolMapping:
    """Tests for FrameSymbolMapping schema."""

    def test_creation_with_defaults(self) -> None:
        """Test creating a mapping with default values."""
        mapping = FrameSymbolMapping(frame_name="MyClass.Method")
        assert mapping.frame_name == "MyClass.Method"
        assert mapping.symbol_id is None
        assert mapping.confidence == 1.0
        assert mapping.last_updated is None

    def test_creation_with_all_fields(self) -> None:
        """Test creating a mapping with all fields."""
        mapping = FrameSymbolMapping(
            frame_name="MyClass.Method",
            symbol_id="node-123",
            confidence=0.85,
            last_updated="2026-01-30T12:00:00Z",
        )
        assert mapping.frame_name == "MyClass.Method"
        assert mapping.symbol_id == "node-123"
        assert mapping.confidence == 0.85
        assert mapping.last_updated == "2026-01-30T12:00:00Z"

    def test_confidence_validation(self) -> None:
        """Test that confidence is validated to 0.0-1.0 range."""
        # Valid values
        FrameSymbolMapping(frame_name="test", confidence=0.0)
        FrameSymbolMapping(frame_name="test", confidence=0.5)
        FrameSymbolMapping(frame_name="test", confidence=1.0)

        # Invalid values should raise
        with pytest.raises(ValueError):
            FrameSymbolMapping(frame_name="test", confidence=-0.1)
        with pytest.raises(ValueError):
            FrameSymbolMapping(frame_name="test", confidence=1.1)


class TestFrameSymbolMappingStorage:
    """Tests for frame symbol mapping storage operations."""

    def test_set_and_get_mapping(self, storage: ProfileStorage) -> None:
        """Test setting and retrieving a symbol mapping."""
        storage.set_symbol_mapping("main", "node-main-123")

        mapping = storage.get_symbol_mapping("main")
        assert mapping is not None
        assert mapping.frame_name == "main"
        assert mapping.symbol_id == "node-main-123"
        assert mapping.confidence == 1.0
        assert mapping.last_updated is not None

    def test_set_mapping_with_confidence(self, storage: ProfileStorage) -> None:
        """Test setting a mapping with custom confidence."""
        storage.set_symbol_mapping("fuzzy_match", "node-456", confidence=0.75)

        mapping = storage.get_symbol_mapping("fuzzy_match")
        assert mapping is not None
        assert mapping.confidence == 0.75

    def test_update_existing_mapping(self, storage: ProfileStorage) -> None:
        """Test that setting a mapping updates an existing one."""
        storage.set_symbol_mapping("func", "old-symbol")
        storage.set_symbol_mapping("func", "new-symbol", confidence=0.9)

        mapping = storage.get_symbol_mapping("func")
        assert mapping is not None
        assert mapping.symbol_id == "new-symbol"
        assert mapping.confidence == 0.9

    def test_get_nonexistent_mapping(self, storage: ProfileStorage) -> None:
        """Test getting a mapping that doesn't exist."""
        mapping = storage.get_symbol_mapping("nonexistent")
        assert mapping is None

    def test_delete_mapping(self, storage: ProfileStorage) -> None:
        """Test deleting a symbol mapping."""
        storage.set_symbol_mapping("to_delete", "node-123")
        assert storage.get_symbol_mapping("to_delete") is not None

        deleted = storage.delete_symbol_mapping("to_delete")
        assert deleted is True
        assert storage.get_symbol_mapping("to_delete") is None

    def test_delete_nonexistent_mapping(self, storage: ProfileStorage) -> None:
        """Test deleting a nonexistent mapping returns False."""
        deleted = storage.delete_symbol_mapping("nonexistent")
        assert deleted is False

    def test_get_all_mappings(self, storage: ProfileStorage) -> None:
        """Test listing all mappings."""
        storage.set_symbol_mapping("func1", "node-1", confidence=1.0)
        storage.set_symbol_mapping("func2", "node-2", confidence=0.8)
        storage.set_symbol_mapping("func3", "node-3", confidence=0.6)

        mappings = storage.get_symbol_mappings()
        assert len(mappings) == 3

    def test_get_mappings_with_min_confidence(self, storage: ProfileStorage) -> None:
        """Test filtering mappings by minimum confidence."""
        storage.set_symbol_mapping("high", "node-1", confidence=1.0)
        storage.set_symbol_mapping("medium", "node-2", confidence=0.7)
        storage.set_symbol_mapping("low", "node-3", confidence=0.4)

        mappings = storage.get_symbol_mappings(min_confidence=0.6)
        assert len(mappings) == 2
        names = {m.frame_name for m in mappings}
        assert names == {"high", "medium"}

    def test_get_mappings_with_limit(self, storage: ProfileStorage) -> None:
        """Test limiting mapping results."""
        for i in range(5):
            storage.set_symbol_mapping(f"func{i}", f"node-{i}")

        mappings = storage.get_symbol_mappings(limit=3)
        assert len(mappings) == 3

    def test_clear_all_mappings(self, storage: ProfileStorage) -> None:
        """Test clearing all mappings."""
        storage.set_symbol_mapping("func1", "node-1")
        storage.set_symbol_mapping("func2", "node-2")

        count = storage.clear_symbol_mappings()
        assert count == 2
        assert storage.get_symbol_mappings() == []

    def test_get_unmapped_frames(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test finding frames without symbol mappings."""
        storage.create_profile(sample_profile)

        # Initially, both frames are unmapped
        unmapped = storage.get_unmapped_frames()
        assert len(unmapped) == 2
        assert set(unmapped) == {"main", "helper"}

        # Map one frame
        storage.set_symbol_mapping("main", "node-main")

        # Now only helper is unmapped
        unmapped = storage.get_unmapped_frames()
        assert unmapped == ["helper"]

    def test_get_unmapped_frames_by_profile(
        self, storage: ProfileStorage
    ) -> None:
        """Test finding unmapped frames scoped to a specific profile."""
        # Create two profiles with different functions
        profile1 = Profile(
            id="p1",
            name="Profile 1",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[
                FunctionStats(
                    profile_id="p1",
                    frame_index=0,
                    name="func_a",
                    self_weight=100,
                    total_weight=100,
                    call_count=1,
                ),
            ],
        )
        profile2 = Profile(
            id="p2",
            name="Profile 2",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[
                FunctionStats(
                    profile_id="p2",
                    frame_index=0,
                    name="func_b",
                    self_weight=100,
                    total_weight=100,
                    call_count=1,
                ),
            ],
        )
        storage.create_profile(profile1)
        storage.create_profile(profile2)

        # Map func_a
        storage.set_symbol_mapping("func_a", "node-a")

        # Unmapped for p1 should be empty
        unmapped_p1 = storage.get_unmapped_frames(profile_id="p1")
        assert unmapped_p1 == []

        # Unmapped for p2 should contain func_b
        unmapped_p2 = storage.get_unmapped_frames(profile_id="p2")
        assert unmapped_p2 == ["func_b"]

    def test_apply_mappings_to_profile(
        self, storage: ProfileStorage, sample_profile: Profile
    ) -> None:
        """Test applying cached mappings to a profile."""
        storage.create_profile(sample_profile)

        # Create mappings
        storage.set_symbol_mapping("main", "node-main-xyz")
        storage.set_symbol_mapping("helper", "node-helper-abc")

        # Apply mappings
        count = storage.apply_mappings_to_profile(sample_profile.id)
        assert count == 2

        # Verify mappings were applied
        profile = storage.get_profile(sample_profile.id)
        assert profile is not None
        stats_by_name = {s.name: s for s in profile.function_stats}
        assert stats_by_name["main"].symbol_id == "node-main-xyz"
        assert stats_by_name["helper"].symbol_id == "node-helper-abc"

    def test_apply_mappings_partial(self, storage: ProfileStorage) -> None:
        """Test applying mappings when only some frames are mapped."""
        profile = Profile(
            id="partial-test",
            name="Partial Test",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[
                FunctionStats(
                    profile_id="partial-test",
                    frame_index=0,
                    name="mapped_func",
                    self_weight=100,
                    total_weight=100,
                    call_count=1,
                ),
                FunctionStats(
                    profile_id="partial-test",
                    frame_index=1,
                    name="unmapped_func",
                    self_weight=100,
                    total_weight=100,
                    call_count=1,
                ),
            ],
        )
        storage.create_profile(profile)

        # Only map one function
        storage.set_symbol_mapping("mapped_func", "node-mapped")

        count = storage.apply_mappings_to_profile("partial-test")
        assert count == 1

        # Verify
        result = storage.get_profile("partial-test")
        assert result is not None
        stats_by_name = {s.name: s for s in result.function_stats}
        assert stats_by_name["mapped_func"].symbol_id == "node-mapped"
        assert stats_by_name["unmapped_func"].symbol_id is None
