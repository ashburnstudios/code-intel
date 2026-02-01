"""Speedscope profile format parser.

Parses speedscope JSON format (https://www.speedscope.app/file-format-schema.json)
and converts it to code-intel's Profile schema.

Supports:
- Sampled profiles (stack snapshots with weights)
- Evented profiles (open/close frame events)
- Multiple profiles per file
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code_intel.profile.schema import (
    Frame,
    FunctionStats,
    Profile,
    ProfileMetadata,
    ProfileType,
    ValueUnit,
)


class SpeedscopeParser:
    """Parser for speedscope JSON profile format.

    Example:
        parser = SpeedscopeParser()
        profiles = parser.parse_file(Path("profile.speedscope.json"))
        for profile in profiles:
            print(f"{profile.name}: {len(profile.frames)} frames")
    """

    # Mapping from speedscope units to our ValueUnit enum
    _UNIT_MAP = {
        "nanoseconds": ValueUnit.NANOSECONDS,
        "microseconds": ValueUnit.MICROSECONDS,
        "milliseconds": ValueUnit.MILLISECONDS,
        "seconds": ValueUnit.SECONDS,
        "bytes": ValueUnit.BYTES,
        "none": ValueUnit.NONE,
    }

    def parse_file(
        self,
        path: Path | str,
        *,
        repo_path: str | None = None,
        metadata: ProfileMetadata | None = None,
    ) -> list[Profile]:
        """Parse a speedscope JSON file.

        Args:
            path: Path to the speedscope JSON file.
            repo_path: Optional repository path to associate with profiles.
            metadata: Optional metadata to attach to all profiles.

        Returns:
            List of Profile objects (one per profile in the file).

        Raises:
            ValueError: If the file is not a valid speedscope format.
            FileNotFoundError: If the file does not exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Profile file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self.parse_data(
            data,
            source_file=str(path),
            repo_path=repo_path,
            metadata=metadata,
        )

    def parse_data(
        self,
        data: dict[str, Any],
        *,
        source_file: str | None = None,
        repo_path: str | None = None,
        metadata: ProfileMetadata | None = None,
    ) -> list[Profile]:
        """Parse speedscope JSON data.

        Args:
            data: Parsed JSON data from a speedscope file.
            source_file: Original file path (for reference).
            repo_path: Optional repository path to associate with profiles.
            metadata: Optional metadata to attach to all profiles.

        Returns:
            List of Profile objects.

        Raises:
            ValueError: If the data is not valid speedscope format.
        """
        # Validate basic structure
        if "profiles" not in data or "shared" not in data:
            raise ValueError("Invalid speedscope format: missing 'profiles' or 'shared'")

        shared = data["shared"]
        if "frames" not in shared:
            raise ValueError("Invalid speedscope format: missing 'shared.frames'")

        # Parse shared frames
        shared_frames = self._parse_frames(shared["frames"])

        # Get file-level name if present
        file_name = data.get("name", "")
        exporter = data.get("exporter", "")

        profiles = []
        for idx, profile_data in enumerate(data["profiles"]):
            profile = self._parse_profile(
                profile_data,
                shared_frames=shared_frames,
                profile_index=idx,
                file_name=file_name,
                exporter=exporter,
                source_file=source_file,
                repo_path=repo_path,
                base_metadata=metadata,
            )
            profiles.append(profile)

        return profiles

    def _parse_frames(self, frames_data: list[dict[str, Any]]) -> list[Frame]:
        """Parse the shared frames array."""
        frames = []
        for frame_data in frames_data:
            frame = Frame(
                name=frame_data.get("name", "<unknown>"),
                file=frame_data.get("file"),
                line=frame_data.get("line"),
                col=frame_data.get("col"),
            )
            frames.append(frame)
        return frames

    def _parse_profile(
        self,
        profile_data: dict[str, Any],
        *,
        shared_frames: list[Frame],
        profile_index: int,
        file_name: str,
        exporter: str,
        source_file: str | None,
        repo_path: str | None,
        base_metadata: ProfileMetadata | None,
    ) -> Profile:
        """Parse a single profile from the profiles array."""
        profile_type_str = profile_data.get("type", "sampled")
        profile_type = (
            ProfileType.EVENTED
            if profile_type_str == "evented"
            else ProfileType.SAMPLED
        )

        # Get profile name
        profile_name = profile_data.get("name", f"Profile {profile_index + 1}")
        if file_name and not profile_name.startswith(file_name):
            profile_name = f"{file_name} - {profile_name}"

        # Parse unit
        unit_str = profile_data.get("unit", "none")
        unit = self._UNIT_MAP.get(unit_str.lower(), ValueUnit.NONE)

        # Timing bounds
        start_value = profile_data.get("startValue", 0)
        end_value = profile_data.get("endValue", 0)

        # Generate unique ID
        profile_id = str(uuid.uuid4())

        # Build metadata
        if base_metadata:
            metadata = base_metadata.model_copy()
        else:
            metadata = ProfileMetadata()

        if exporter:
            metadata.extra["exporter"] = exporter

        # Compute function stats based on profile type
        if profile_type == ProfileType.SAMPLED:
            function_stats = self._compute_sampled_stats(
                profile_data, shared_frames, profile_id
            )
        else:
            function_stats = self._compute_evented_stats(
                profile_data, shared_frames, profile_id
            )

        return Profile(
            id=profile_id,
            name=profile_name,
            profile_type=profile_type,
            unit=unit,
            start_value=start_value,
            end_value=end_value,
            frames=shared_frames.copy(),
            function_stats=function_stats,
            metadata=metadata,
            repo_path=repo_path,
            source_file=source_file,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _compute_sampled_stats(
        self,
        profile_data: dict[str, Any],
        frames: list[Frame],
        profile_id: str,
    ) -> list[FunctionStats]:
        """Compute function statistics from a sampled profile.

        In a sampled profile:
        - samples: array of stack traces (each is an array of frame indices)
        - weights: parallel array of sample weights

        Self time = time when this frame is at the top of the stack
        Total time = time when this frame is anywhere in the stack
        """
        samples = profile_data.get("samples", [])
        weights = profile_data.get("weights", [])

        if not samples:
            return []

        # Ensure weights match samples
        if len(weights) != len(samples):
            # Default to weight of 1 per sample
            weights = [1] * len(samples)

        # Track per-frame statistics
        # frame_index -> {self_weight, total_weight, call_count}
        stats_map: dict[int, dict[str, float | int]] = {}

        total_weight = sum(weights)

        for sample_idx, sample in enumerate(samples):
            weight = weights[sample_idx]

            if not sample:
                continue

            # All frames in the stack get total time
            seen_in_stack: set[int] = set()
            for frame_idx in sample:
                if frame_idx not in stats_map:
                    stats_map[frame_idx] = {
                        "self_weight": 0.0,
                        "total_weight": 0.0,
                        "call_count": 0,
                    }
                if frame_idx not in seen_in_stack:
                    stats_map[frame_idx]["total_weight"] += weight
                    seen_in_stack.add(frame_idx)

            # Top of stack (last element) gets self time
            top_frame = sample[-1]
            stats_map[top_frame]["self_weight"] += weight
            stats_map[top_frame]["call_count"] += 1

        # Convert to FunctionStats objects
        result = []
        for frame_idx, stats in stats_map.items():
            if frame_idx >= len(frames):
                continue

            frame = frames[frame_idx]
            self_pct = (stats["self_weight"] / total_weight * 100) if total_weight else 0
            total_pct = (stats["total_weight"] / total_weight * 100) if total_weight else 0

            result.append(
                FunctionStats(
                    profile_id=profile_id,
                    frame_index=frame_idx,
                    name=frame.name,
                    file=frame.file,
                    line=frame.line,
                    self_weight=stats["self_weight"],
                    total_weight=stats["total_weight"],
                    call_count=int(stats["call_count"]),
                    self_percentage=self_pct,
                    total_percentage=total_pct,
                )
            )

        # Sort by self weight descending
        result.sort(key=lambda s: s.self_weight, reverse=True)
        return result

    def _compute_evented_stats(
        self,
        profile_data: dict[str, Any],
        frames: list[Frame],
        profile_id: str,
    ) -> list[FunctionStats]:
        """Compute function statistics from an evented profile.

        In an evented profile:
        - events: array of {type, at, frame} objects
        - type: 'O' for open, 'C' for close
        - at: timestamp
        - frame: frame index

        Self time = time when this frame is the most recent open frame
        Total time = time between open and close
        """
        events = profile_data.get("events", [])
        if not events:
            return []

        # Stack of open frames: [(frame_idx, open_time)]
        stack: list[tuple[int, float]] = []

        # Track per-frame statistics
        stats_map: dict[int, dict[str, float | int]] = {}

        # Track when each frame was last the top of stack (for self time)
        last_top_time: float | None = None

        for event in events:
            event_type = event.get("type")
            timestamp = event.get("at", 0)
            frame_idx = event.get("frame", 0)

            if frame_idx not in stats_map:
                stats_map[frame_idx] = {
                    "self_weight": 0.0,
                    "total_weight": 0.0,
                    "call_count": 0,
                }

            if event_type == "O":  # Open frame
                # If there was a previous top frame, add self time to it
                if stack and last_top_time is not None:
                    prev_top = stack[-1][0]
                    stats_map[prev_top]["self_weight"] += timestamp - last_top_time

                stack.append((frame_idx, timestamp))
                stats_map[frame_idx]["call_count"] += 1
                last_top_time = timestamp

            elif event_type == "C":  # Close frame
                if stack and stack[-1][0] == frame_idx:
                    _, open_time = stack.pop()
                    # Add total time
                    stats_map[frame_idx]["total_weight"] += timestamp - open_time
                    # Add self time (from last_top_time to now)
                    if last_top_time is not None:
                        stats_map[frame_idx]["self_weight"] += timestamp - last_top_time
                    # Update last_top_time to now (new frame at top of stack)
                    last_top_time = timestamp

        # Calculate total profile duration for percentages
        start_value = profile_data.get("startValue", 0)
        end_value = profile_data.get("endValue", 0)
        total_duration = end_value - start_value

        # Convert to FunctionStats objects
        result = []
        for frame_idx, stats in stats_map.items():
            if frame_idx >= len(frames):
                continue

            frame = frames[frame_idx]
            self_pct = (stats["self_weight"] / total_duration * 100) if total_duration else 0
            total_pct = (stats["total_weight"] / total_duration * 100) if total_duration else 0

            result.append(
                FunctionStats(
                    profile_id=profile_id,
                    frame_index=frame_idx,
                    name=frame.name,
                    file=frame.file,
                    line=frame.line,
                    self_weight=stats["self_weight"],
                    total_weight=stats["total_weight"],
                    call_count=int(stats["call_count"]),
                    self_percentage=self_pct,
                    total_percentage=total_pct,
                )
            )

        # Sort by self weight descending
        result.sort(key=lambda s: s.self_weight, reverse=True)
        return result
