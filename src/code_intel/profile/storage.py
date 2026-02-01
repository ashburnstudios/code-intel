"""SQLite storage layer for performance profiles."""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from code_intel.profile.schema import (
    Frame,
    FunctionDelta,
    FunctionStats,
    Profile,
    ProfileComparison,
    ProfileMetadata,
    ProfileType,
    ValueUnit,
)

# Schema version for migration support
PROFILE_SCHEMA_VERSION = 1

# SQL statements for schema creation
_CREATE_PROFILE_SCHEMA = """
-- Profile schema version tracking
CREATE TABLE IF NOT EXISTS profile_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Profiles table: metadata about each profiling session
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile_type TEXT NOT NULL,
    unit TEXT NOT NULL,
    start_value REAL NOT NULL DEFAULT 0,
    end_value REAL NOT NULL DEFAULT 0,
    repo_path TEXT,
    source_file TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Frames table: unique function/method frames
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL,
    name TEXT NOT NULL,
    file TEXT,
    line INTEGER,
    col INTEGER,
    UNIQUE(profile_id, frame_index)
);

-- Function stats table: aggregated metrics per function per profile
CREATE TABLE IF NOT EXISTS function_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL,
    name TEXT NOT NULL,
    file TEXT,
    line INTEGER,
    self_weight REAL NOT NULL DEFAULT 0,
    total_weight REAL NOT NULL DEFAULT 0,
    call_count INTEGER NOT NULL DEFAULT 0,
    self_percentage REAL NOT NULL DEFAULT 0,
    total_percentage REAL NOT NULL DEFAULT 0,
    symbol_id TEXT,
    UNIQUE(profile_id, frame_index)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_profiles_repo ON profiles(repo_path);
CREATE INDEX IF NOT EXISTS idx_profiles_created ON profiles(created_at);
CREATE INDEX IF NOT EXISTS idx_frames_profile ON frames(profile_id);
CREATE INDEX IF NOT EXISTS idx_frames_name ON frames(name);
CREATE INDEX IF NOT EXISTS idx_stats_profile ON function_stats(profile_id);
CREATE INDEX IF NOT EXISTS idx_stats_name ON function_stats(name);
CREATE INDEX IF NOT EXISTS idx_stats_self_weight ON function_stats(self_weight DESC);
CREATE INDEX IF NOT EXISTS idx_stats_total_weight ON function_stats(total_weight DESC);
CREATE INDEX IF NOT EXISTS idx_stats_symbol ON function_stats(symbol_id);
"""


class ProfileStorage:
    """SQLite-backed storage for performance profiles.

    Provides persistent storage for profile data with efficient querying
    for hotspots, comparisons, and trends.

    Example:
        storage = ProfileStorage(Path("project/.code-intel.db"))
        storage.create_profile(profile)
        hotspots = storage.get_top_functions(profile_id, limit=10)
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise the storage.

        Args:
            db_path: Path to the SQLite database file. If None, uses
                     an in-memory database (useful for testing).
        """
        self._is_memory = db_path is None
        if self._is_memory:
            self._db_path = ":memory:"
        else:
            self._db_path = str(Path(db_path).resolve())

        # Thread-local storage for connections
        self._local = threading.local()

        # Initialise schema in the current thread
        self._initialise_schema()

    def _get_thread_connection(self) -> sqlite3.Connection:
        """Get or create a connection for the current thread."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
            self._local.needs_schema_init = self._is_memory

        return self._local.conn

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with proper configuration."""
        conn = self._get_thread_connection()

        # For in-memory databases, new threads need schema initialisation
        if getattr(self._local, "needs_schema_init", False):
            conn.executescript(_CREATE_PROFILE_SCHEMA)
            conn.execute(
                "INSERT INTO profile_schema_version (version) VALUES (?)",
                (PROFILE_SCHEMA_VERSION,),
            )
            conn.commit()
            self._local.needs_schema_init = False

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _initialise_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._get_connection() as conn:
            conn.executescript(_CREATE_PROFILE_SCHEMA)

            # Check and update schema version
            cursor = conn.execute(
                "SELECT version FROM profile_schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            current_version = row["version"] if row else 0

            if current_version < PROFILE_SCHEMA_VERSION:
                self._run_migrations(conn, current_version, PROFILE_SCHEMA_VERSION)
                conn.execute(
                    "INSERT INTO profile_schema_version (version) VALUES (?)",
                    (PROFILE_SCHEMA_VERSION,),
                )

    def _run_migrations(
        self, conn: sqlite3.Connection, from_version: int, to_version: int
    ) -> None:
        """Run schema migrations between versions."""
        # Future migrations will be added here
        pass

    # =========================================================================
    # Profile CRUD
    # =========================================================================

    def create_profile(self, profile: Profile) -> None:
        """Insert a profile with all its frames and stats.

        Args:
            profile: Profile to store.
        """
        with self._get_connection() as conn:
            # Insert profile metadata
            conn.execute(
                """
                INSERT OR REPLACE INTO profiles (
                    id, name, profile_type, unit, start_value, end_value,
                    repo_path, source_file, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.id,
                    profile.name,
                    profile.profile_type.value,
                    profile.unit.value,
                    profile.start_value,
                    profile.end_value,
                    profile.repo_path,
                    profile.source_file,
                    json.dumps(profile.metadata.model_dump()),
                    profile.created_at or datetime.now(timezone.utc).isoformat(),
                ),
            )

            # Insert frames
            for idx, frame in enumerate(profile.frames):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO frames (
                        profile_id, frame_index, name, file, line, col
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (profile.id, idx, frame.name, frame.file, frame.line, frame.col),
                )

            # Insert function stats
            for stats in profile.function_stats:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO function_stats (
                        profile_id, frame_index, name, file, line,
                        self_weight, total_weight, call_count,
                        self_percentage, total_percentage, symbol_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.id,
                        stats.frame_index,
                        stats.name,
                        stats.file,
                        stats.line,
                        stats.self_weight,
                        stats.total_weight,
                        stats.call_count,
                        stats.self_percentage,
                        stats.total_percentage,
                        stats.symbol_id,
                    ),
                )

    def get_profile(self, profile_id: str) -> Profile | None:
        """Retrieve a profile by ID.

        Args:
            profile_id: Unique identifier of the profile.

        Returns:
            Profile if found, None otherwise.
        """
        with self._get_connection() as conn:
            # Get profile metadata
            cursor = conn.execute(
                "SELECT * FROM profiles WHERE id = ?", (profile_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Get frames
            frames_cursor = conn.execute(
                "SELECT * FROM frames WHERE profile_id = ? ORDER BY frame_index",
                (profile_id,),
            )
            frames = [
                Frame(
                    name=f["name"],
                    file=f["file"],
                    line=f["line"],
                    col=f["col"],
                )
                for f in frames_cursor.fetchall()
            ]

            # Get function stats
            stats_cursor = conn.execute(
                "SELECT * FROM function_stats WHERE profile_id = ?",
                (profile_id,),
            )
            function_stats = [
                self._row_to_function_stats(s) for s in stats_cursor.fetchall()
            ]

            # Parse metadata
            metadata_dict = json.loads(row["metadata"]) if row["metadata"] else {}
            metadata = ProfileMetadata(**metadata_dict)

            return Profile(
                id=row["id"],
                name=row["name"],
                profile_type=ProfileType(row["profile_type"]),
                unit=ValueUnit(row["unit"]),
                start_value=row["start_value"],
                end_value=row["end_value"],
                frames=frames,
                function_stats=function_stats,
                metadata=metadata,
                repo_path=row["repo_path"],
                source_file=row["source_file"],
                created_at=row["created_at"],
            )

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a profile and all associated data.

        Args:
            profile_id: ID of the profile to delete.

        Returns:
            True if deleted, False if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM profiles WHERE id = ?", (profile_id,)
            )
            return cursor.rowcount > 0

    def list_profiles(
        self,
        repo_path: str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Profile]:
        """List profiles, optionally filtered by repository.

        Args:
            repo_path: Optional repository path filter.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of Profile objects (without full frames/stats loaded).
        """
        query = "SELECT * FROM profiles"
        params: list[str | int] = []

        if repo_path:
            query += " WHERE repo_path = ?"
            params.append(repo_path)

        query += " ORDER BY created_at DESC"

        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        elif offset > 0:
            query += " LIMIT -1 OFFSET ?"
            params.append(offset)

        profiles = []
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                metadata_dict = json.loads(row["metadata"]) if row["metadata"] else {}
                profiles.append(
                    Profile(
                        id=row["id"],
                        name=row["name"],
                        profile_type=ProfileType(row["profile_type"]),
                        unit=ValueUnit(row["unit"]),
                        start_value=row["start_value"],
                        end_value=row["end_value"],
                        frames=[],  # Not loaded for listing
                        function_stats=[],  # Not loaded for listing
                        metadata=ProfileMetadata(**metadata_dict),
                        repo_path=row["repo_path"],
                        source_file=row["source_file"],
                        created_at=row["created_at"],
                    )
                )

        return profiles

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_top_functions(
        self,
        profile_id: str,
        *,
        limit: int = 10,
        by: str = "self",
    ) -> list[FunctionStats]:
        """Get the hottest functions in a profile.

        Args:
            profile_id: ID of the profile to query.
            limit: Maximum number of results.
            by: Sort key - 'self' for self time, 'total' for total time.

        Returns:
            List of FunctionStats sorted by the specified metric.
        """
        order_col = "self_weight" if by == "self" else "total_weight"
        query = f"""
            SELECT * FROM function_stats
            WHERE profile_id = ?
            ORDER BY {order_col} DESC
            LIMIT ?
        """

        with self._get_connection() as conn:
            cursor = conn.execute(query, (profile_id, limit))
            return [self._row_to_function_stats(row) for row in cursor.fetchall()]

    def get_function_trend(
        self,
        function_name: str,
        repo_path: str | None = None,
        *,
        limit: int = 10,
    ) -> list[tuple[Profile, FunctionStats]]:
        """Get a function's performance over time across profiles.

        Args:
            function_name: Name of the function to track.
            repo_path: Optional repository path filter.
            limit: Maximum number of profiles to include.

        Returns:
            List of (Profile, FunctionStats) tuples, ordered by profile date.
        """
        # Use explicit column aliases to avoid ambiguity in the JOIN
        query = """
            SELECT
                p.id as p_id,
                p.name as p_name,
                p.profile_type as p_profile_type,
                p.unit as p_unit,
                p.start_value as p_start_value,
                p.end_value as p_end_value,
                p.repo_path as p_repo_path,
                p.source_file as p_source_file,
                p.metadata as p_metadata,
                p.created_at as p_created_at,
                fs.profile_id as fs_profile_id,
                fs.frame_index as fs_frame_index,
                fs.name as fs_name,
                fs.file as fs_file,
                fs.line as fs_line,
                fs.self_weight as fs_self_weight,
                fs.total_weight as fs_total_weight,
                fs.call_count as fs_call_count,
                fs.self_percentage as fs_self_percentage,
                fs.total_percentage as fs_total_percentage,
                fs.symbol_id as fs_symbol_id
            FROM profiles p
            JOIN function_stats fs ON p.id = fs.profile_id
            WHERE fs.name = ?
        """
        params: list[str | int] = [function_name]

        if repo_path:
            query += " AND p.repo_path = ?"
            params.append(repo_path)

        query += " ORDER BY p.created_at DESC LIMIT ?"
        params.append(limit)

        results = []
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                metadata_dict = json.loads(row["p_metadata"]) if row["p_metadata"] else {}
                profile = Profile(
                    id=row["p_id"],
                    name=row["p_name"],
                    profile_type=ProfileType(row["p_profile_type"]),
                    unit=ValueUnit(row["p_unit"]),
                    start_value=row["p_start_value"],
                    end_value=row["p_end_value"],
                    metadata=ProfileMetadata(**metadata_dict),
                    repo_path=row["p_repo_path"],
                    source_file=row["p_source_file"],
                    created_at=row["p_created_at"],
                )
                stats = FunctionStats(
                    profile_id=row["fs_profile_id"],
                    frame_index=row["fs_frame_index"],
                    name=row["fs_name"],
                    file=row["fs_file"],
                    line=row["fs_line"],
                    self_weight=row["fs_self_weight"],
                    total_weight=row["fs_total_weight"],
                    call_count=row["fs_call_count"],
                    self_percentage=row["fs_self_percentage"],
                    total_percentage=row["fs_total_percentage"],
                    symbol_id=row["fs_symbol_id"],
                )
                results.append((profile, stats))

        return results

    def compare_profiles(
        self,
        before_id: str,
        after_id: str,
        *,
        threshold_pct: float = 5.0,
    ) -> ProfileComparison | None:
        """Compare two profiles to find regressions and improvements.

        Args:
            before_id: ID of the 'before' profile.
            after_id: ID of the 'after' profile.
            threshold_pct: Minimum percentage change to report.

        Returns:
            ProfileComparison with deltas, or None if profiles not found.
        """
        before = self.get_profile(before_id)
        after = self.get_profile(after_id)

        if not before or not after:
            return None

        # Build lookup maps
        before_stats = {s.name: s for s in before.function_stats}
        after_stats = {s.name: s for s in after.function_stats}

        all_names = set(before_stats.keys()) | set(after_stats.keys())

        regressions: list[FunctionDelta] = []
        improvements: list[FunctionDelta] = []
        new_functions: list[FunctionStats] = []
        removed_functions: list[FunctionStats] = []

        for name in all_names:
            b = before_stats.get(name)
            a = after_stats.get(name)

            if b and not a:
                removed_functions.append(b)
            elif a and not b:
                new_functions.append(a)
            elif b and a:
                delta = FunctionDelta(
                    name=name,
                    file=a.file or b.file,
                    before_self_weight=b.self_weight,
                    before_total_weight=b.total_weight,
                    before_call_count=b.call_count,
                    after_self_weight=a.self_weight,
                    after_total_weight=a.total_weight,
                    after_call_count=a.call_count,
                    self_weight_delta=a.self_weight - b.self_weight,
                    total_weight_delta=a.total_weight - b.total_weight,
                )

                # Calculate percentage changes
                if b.self_weight > 0:
                    delta.self_weight_change_pct = (
                        (a.self_weight - b.self_weight) / b.self_weight * 100
                    )
                if b.total_weight > 0:
                    delta.total_weight_change_pct = (
                        (a.total_weight - b.total_weight) / b.total_weight * 100
                    )

                # Classify based on threshold
                if (
                    delta.self_weight_change_pct is not None
                    and delta.self_weight_change_pct > threshold_pct
                ):
                    regressions.append(delta)
                elif (
                    delta.self_weight_change_pct is not None
                    and delta.self_weight_change_pct < -threshold_pct
                ):
                    improvements.append(delta)

        # Sort by absolute impact
        regressions.sort(key=lambda d: d.self_weight_delta, reverse=True)
        improvements.sort(key=lambda d: d.self_weight_delta)

        # Calculate overall comparison
        duration_delta = after.duration - before.duration
        duration_change_pct = None
        if before.duration > 0:
            duration_change_pct = duration_delta / before.duration * 100

        return ProfileComparison(
            before_profile_id=before_id,
            after_profile_id=after_id,
            before_profile_name=before.name,
            after_profile_name=after.name,
            before_duration=before.duration,
            after_duration=after.duration,
            duration_delta=duration_delta,
            duration_change_pct=duration_change_pct,
            regressions=regressions,
            improvements=improvements,
            new_functions=new_functions,
            removed_functions=removed_functions,
        )

    def get_functions_by_symbol(
        self,
        symbol_id: str,
        *,
        limit: int = 10,
    ) -> list[tuple[Profile, FunctionStats]]:
        """Find profile data for a specific code symbol.

        This enables queries like "show me performance data for this function"
        by linking profile frames to code-intel symbols.

        Args:
            symbol_id: ID of a node in the code graph.
            limit: Maximum number of results.

        Returns:
            List of (Profile, FunctionStats) tuples.
        """
        # Use explicit column aliases to avoid ambiguity in the JOIN
        query = """
            SELECT
                p.id as p_id,
                p.name as p_name,
                p.profile_type as p_profile_type,
                p.unit as p_unit,
                p.start_value as p_start_value,
                p.end_value as p_end_value,
                p.repo_path as p_repo_path,
                p.source_file as p_source_file,
                p.metadata as p_metadata,
                p.created_at as p_created_at,
                fs.profile_id as fs_profile_id,
                fs.frame_index as fs_frame_index,
                fs.name as fs_name,
                fs.file as fs_file,
                fs.line as fs_line,
                fs.self_weight as fs_self_weight,
                fs.total_weight as fs_total_weight,
                fs.call_count as fs_call_count,
                fs.self_percentage as fs_self_percentage,
                fs.total_percentage as fs_total_percentage,
                fs.symbol_id as fs_symbol_id
            FROM profiles p
            JOIN function_stats fs ON p.id = fs.profile_id
            WHERE fs.symbol_id = ?
            ORDER BY p.created_at DESC
            LIMIT ?
        """

        results = []
        with self._get_connection() as conn:
            cursor = conn.execute(query, (symbol_id, limit))
            for row in cursor.fetchall():
                metadata_dict = json.loads(row["p_metadata"]) if row["p_metadata"] else {}
                profile = Profile(
                    id=row["p_id"],
                    name=row["p_name"],
                    profile_type=ProfileType(row["p_profile_type"]),
                    unit=ValueUnit(row["p_unit"]),
                    start_value=row["p_start_value"],
                    end_value=row["p_end_value"],
                    metadata=ProfileMetadata(**metadata_dict),
                    repo_path=row["p_repo_path"],
                    source_file=row["p_source_file"],
                    created_at=row["p_created_at"],
                )
                stats = FunctionStats(
                    profile_id=row["fs_profile_id"],
                    frame_index=row["fs_frame_index"],
                    name=row["fs_name"],
                    file=row["fs_file"],
                    line=row["fs_line"],
                    self_weight=row["fs_self_weight"],
                    total_weight=row["fs_total_weight"],
                    call_count=row["fs_call_count"],
                    self_percentage=row["fs_self_percentage"],
                    total_percentage=row["fs_total_percentage"],
                    symbol_id=row["fs_symbol_id"],
                )
                results.append((profile, stats))

        return results

    def update_symbol_correlations(
        self,
        profile_id: str,
        correlations: dict[int, str],
    ) -> int:
        """Update symbol IDs for function stats in a profile.

        Called after correlating profile frames with code graph nodes.

        Args:
            profile_id: ID of the profile to update.
            correlations: Mapping of frame_index -> symbol_id.

        Returns:
            Number of stats updated.
        """
        count = 0
        with self._get_connection() as conn:
            for frame_index, symbol_id in correlations.items():
                cursor = conn.execute(
                    """
                    UPDATE function_stats
                    SET symbol_id = ?
                    WHERE profile_id = ? AND frame_index = ?
                    """,
                    (symbol_id, profile_id, frame_index),
                )
                count += cursor.rowcount
        return count

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _row_to_function_stats(self, row: sqlite3.Row) -> FunctionStats:
        """Convert a database row to a FunctionStats object."""
        return FunctionStats(
            profile_id=row["profile_id"],
            frame_index=row["frame_index"],
            name=row["name"],
            file=row["file"],
            line=row["line"],
            self_weight=row["self_weight"],
            total_weight=row["total_weight"],
            call_count=row["call_count"],
            self_percentage=row["self_percentage"],
            total_percentage=row["total_percentage"],
            symbol_id=row["symbol_id"],
        )
