from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Deque, Iterable


class ContactState(str, Enum):
    SAFE = "safe"
    NEAR = "near"
    CONTACT_PENDING = "contact_pending"
    CONTACT_EVENT = "contact_event"


@dataclass(frozen=True)
class BinaryMask:
    width: int
    height: int
    packed_bits: bytes

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Mask dimensions must be positive")
        expected_bytes = (self.width * self.height + 7) // 8
        if len(self.packed_bits) != expected_bytes:
            raise ValueError("Packed mask length does not match its dimensions")

    @property
    def area(self) -> int:
        return int.from_bytes(self.packed_bits, "little").bit_count()


@dataclass(frozen=True)
class Detection:
    class_id: int
    confidence: float
    box: tuple[float, float, float, float]
    track_id: int | None
    mask: BinaryMask | None = None
    contact_points: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Detection confidence must be between 0 and 1")
        if len(self.box) != 4 or not all(math.isfinite(value) for value in self.box):
            raise ValueError("Detection box must contain four finite coordinates")
        x1, y1, x2, y2 = self.box
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Detection box must have positive area")
        if any(not math.isfinite(x) or not math.isfinite(y) for x, y in self.contact_points):
            raise ValueError("Contact points must be finite image coordinates")


@dataclass(frozen=True)
class ContactSettings:
    confidence_threshold: float
    contact_overlap_threshold: float
    near_distance_threshold: float
    minimum_contact_duration: float
    required_positive_frames: int
    sliding_window_size: int
    alert_cooldown: float
    painting_class_id: int = 0
    hand_class_id: int = 2
    tool_class_id: int = 3

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        if not 0.0 < self.contact_overlap_threshold <= 1.0:
            raise ValueError("contact_overlap_threshold must be in (0, 1]")
        if self.near_distance_threshold < 0:
            raise ValueError("near_distance_threshold cannot be negative")
        if self.minimum_contact_duration < 0 or self.alert_cooldown < 0:
            raise ValueError("Durations cannot be negative")
        if self.required_positive_frames < 1:
            raise ValueError("required_positive_frames must be positive")
        if self.sliding_window_size < self.required_positive_frames:
            raise ValueError("sliding_window_size must cover required_positive_frames")


@dataclass(frozen=True)
class ContactEvent:
    event: str
    contact_type: str
    confidence: float
    timestamp: str
    painting_id: int
    interaction_id: int
    overlap: float


@dataclass(frozen=True)
class FrameAnalysis:
    state: ContactState
    nearest_distance: float | None
    maximum_overlap: float
    events: tuple[ContactEvent, ...] = ()


@dataclass
class _Observation:
    timestamp: float
    positive: bool
    confidence: float
    overlap: float


@dataclass
class _ContactTrack:
    observations: Deque[_Observation] = field(default_factory=deque)
    armed: bool = True
    last_seen_frame: int = 0


def _box_gap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    horizontal = max(first[0] - second[2], second[0] - first[2], 0.0)
    vertical = max(first[1] - second[3], second[1] - first[3], 0.0)
    return math.hypot(horizontal, vertical)


def _box_overlap_ratio(
    interaction: tuple[float, float, float, float],
    painting: tuple[float, float, float, float],
) -> float:
    left = max(interaction[0], painting[0])
    top = max(interaction[1], painting[1])
    right = min(interaction[2], painting[2])
    bottom = min(interaction[3], painting[3])
    if right <= left or bottom <= top:
        return 0.0
    interaction_area = (interaction[2] - interaction[0]) * (interaction[3] - interaction[1])
    return ((right - left) * (bottom - top)) / interaction_area


def _overlap_ratio(interaction: Detection, painting: Detection) -> float:
    interaction_mask = interaction.mask
    painting_mask = painting.mask
    if interaction.contact_points and painting_mask is not None:
        bits = int.from_bytes(painting_mask.packed_bits, "little")
        inside = 0
        for x, y in interaction.contact_points:
            px, py = int(round(x)), int(round(y))
            if 0 <= px < painting_mask.width and 0 <= py < painting_mask.height:
                inside += (bits >> (py * painting_mask.width + px)) & 1
        return inside / len(interaction.contact_points)
    if interaction_mask is None or painting_mask is None:
        return _box_overlap_ratio(interaction.box, painting.box)
    if (interaction_mask.width, interaction_mask.height) != (
        painting_mask.width,
        painting_mask.height,
    ):
        raise ValueError("Painting and interaction masks must use the same frame dimensions")

    interaction_bits = int.from_bytes(interaction_mask.packed_bits, "little")
    painting_bits = int.from_bytes(painting_mask.packed_bits, "little")
    interaction_area = interaction_bits.bit_count()
    if interaction_area == 0:
        return 0.0
    return (interaction_bits & painting_bits).bit_count() / interaction_area


class ContactAnalyzer:
    """Combines mask overlap, tracked identities, and persistence into contact events."""

    def __init__(self, settings: ContactSettings) -> None:
        self.settings = settings
        self._tracks: dict[tuple[int, int, int], _ContactTrack] = {}
        self._frame_index = 0
        self._last_event_at = float("-inf")

    def analyze(
        self,
        detections: Iterable[Detection],
        *,
        monotonic_time: float,
        event_time: datetime | None = None,
    ) -> FrameAnalysis:
        if not math.isfinite(monotonic_time):
            raise ValueError("monotonic_time must be finite")
        event_time = event_time or datetime.now(timezone.utc)
        if event_time.tzinfo is None:
            raise ValueError("event_time must include a timezone")

        visible = [
            detection
            for detection in detections
            if detection.confidence >= self.settings.confidence_threshold
        ]
        paintings = [
            detection
            for detection in visible
            if detection.class_id == self.settings.painting_class_id
            and detection.track_id is not None
        ]
        interactions = [
            detection
            for detection in visible
            if detection.class_id in (self.settings.hand_class_id, self.settings.tool_class_id)
        ]

        self._frame_index += 1
        current_observations: dict[tuple[int, int, int], _Observation] = {}

        nearest_distance: float | None = None
        maximum_overlap = 0.0
        frame_state = ContactState.SAFE
        events: list[ContactEvent] = []
        timestamp = event_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        for interaction in interactions:
            closest = math.inf
            contact_candidate: tuple[Detection, float] | None = None
            for painting in paintings:
                distance = _box_gap(interaction.box, painting.box)
                closest = min(closest, distance)
                overlap = _overlap_ratio(interaction, painting)
                maximum_overlap = max(maximum_overlap, overlap)
                if overlap >= self.settings.contact_overlap_threshold:
                    if contact_candidate is None or overlap > contact_candidate[1]:
                        contact_candidate = (painting, overlap)

            if closest < math.inf:
                nearest_distance = closest if nearest_distance is None else min(nearest_distance, closest)

            if contact_candidate is not None:
                frame_state = ContactState.CONTACT_PENDING
                painting, overlap = contact_candidate
                if interaction.track_id is None:
                    continue
                key = (painting.track_id, interaction.class_id, interaction.track_id)
                observation = _Observation(
                    monotonic_time,
                    True,
                    min(interaction.confidence, painting.confidence),
                    overlap,
                )
                previous = current_observations.get(key)
                if previous is None or observation.overlap > previous.overlap:
                    current_observations[key] = observation
            elif closest <= self.settings.near_distance_threshold and frame_state == ContactState.SAFE:
                frame_state = ContactState.NEAR

        self._append_observations(current_observations, monotonic_time)
        for key, observation in current_observations.items():
            track = self._tracks[key]
            if not self._confirmed(track):
                continue
            frame_state = ContactState.CONTACT_EVENT
            if track.armed and monotonic_time - self._last_event_at >= self.settings.alert_cooldown:
                painting_id, class_id, interaction_id = key
                events.append(
                    ContactEvent(
                        event="painting_contact",
                        contact_type="hand" if class_id == self.settings.hand_class_id else "tool",
                        confidence=observation.confidence,
                        timestamp=timestamp,
                        painting_id=painting_id,
                        interaction_id=interaction_id,
                        overlap=observation.overlap,
                    )
                )
                track.armed = False
                self._last_event_at = monotonic_time

        return FrameAnalysis(frame_state, nearest_distance, maximum_overlap, tuple(events))

    def _append_observations(self, current: dict[tuple[int, int, int], _Observation], now: float) -> None:
        for key in current:
            track = self._tracks.setdefault(key, _ContactTrack())
            track.last_seen_frame = self._frame_index

        for key, track in list(self._tracks.items()):
            track.observations.append(
                current.get(key, _Observation(now, False, 0.0, 0.0))
            )
            self._trim(track)
            if not any(observation.positive for observation in track.observations):
                track.armed = True
            if self._frame_index - track.last_seen_frame > self.settings.sliding_window_size:
                del self._tracks[key]

    def _trim(self, track: _ContactTrack) -> None:
        while len(track.observations) > self.settings.sliding_window_size:
            track.observations.popleft()

    def _confirmed(self, track: _ContactTrack) -> bool:
        positives = [item for item in track.observations if item.positive]
        if not track.observations or not track.observations[-1].positive:
            return False
        if len(positives) < self.settings.required_positive_frames:
            return False
        return positives[-1].timestamp - positives[0].timestamp >= self.settings.minimum_contact_duration
