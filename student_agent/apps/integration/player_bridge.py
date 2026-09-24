"""Player event bridge: protocol, validation, idempotency, segment mapping.

The student classroom view embeds the teacher-side player and listens for
postMessage events. This module owns the protocol so no business component
inlines it.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

PLAYER_READY = "PLAYER_READY"
SCENE_STARTED = "SCENE_STARTED"
SCENE_COMPLETED = "SCENE_COMPLETED"
PLAYBACK_ENDED = "PLAYBACK_ENDED"
PLAYER_ERROR = "PLAYER_ERROR"

KNOWN_EVENTS = {PLAYER_READY, SCENE_STARTED, SCENE_COMPLETED, PLAYBACK_ENDED, PLAYER_ERROR}


class PlayerEventError(ValueError):
    """Invalid or out-of-contract player event."""


@dataclass
class PlayerEvent:
    type: str
    classroom_id: Optional[str] = None
    scene_id: Optional[str] = None
    event_id: Optional[str] = None


@dataclass
class PlayerBridgeState:
    """Idempotent event tracker for one learning session."""
    expected_classroom_id: str
    seen_event_ids: Set[str] = field(default_factory=set)
    completed_scenes: Set[str] = field(default_factory=set)
    ended: bool = False

    def apply(self, event: PlayerEvent) -> Optional[str]:
        """Validate + consume one event.

        Returns the effect for the state machine:
        "segment-advanced" for a new scene completion, "ended" when playback
        finishes, None for informational/duplicate events.
        Duplicate event ids and re-completed scenes are ignored (idempotent).
        """
        if event.type not in KNOWN_EVENTS:
            raise PlayerEventError(f"未知播放器事件：{event.type}")
        if event.classroom_id is not None and event.classroom_id != self.expected_classroom_id:
            raise PlayerEventError(
                f"事件课堂不匹配：{event.classroom_id} != {self.expected_classroom_id}")
        if event.event_id:
            if event.event_id in self.seen_event_ids:
                return None
            self.seen_event_ids.add(event.event_id)
        if event.type == SCENE_COMPLETED:
            if not event.scene_id:
                raise PlayerEventError("SCENE_COMPLETED 缺少 sceneId")
            if event.scene_id in self.completed_scenes:
                return None
            self.completed_scenes.add(event.scene_id)
            return "segment-advanced"
        if event.type == PLAYBACK_ENDED:
            if self.ended:
                return None
            self.ended = True
            return "ended"
        return None


def parse_message(data: Any) -> PlayerEvent:
    """Validate a raw postMessage payload into a PlayerEvent."""
    if not isinstance(data, dict):
        raise PlayerEventError("事件必须是对象")
    event_type = data.get("type")
    if not isinstance(event_type, str) or event_type not in KNOWN_EVENTS:
        raise PlayerEventError(f"未知播放器事件：{event_type}")
    scene_id = data.get("sceneId")
    if scene_id is not None and not isinstance(scene_id, str):
        raise PlayerEventError("sceneId 必须是字符串")
    return PlayerEvent(
        type=event_type,
        classroom_id=data.get("classroomId"),
        scene_id=scene_id,
        event_id=data.get("eventId"),
    )


def segment_for_scene(context, scene_id: str):
    """Map a completed scene id to its segment in the course context."""
    for lesson in context.lessons:
        for segment in lesson.segments:
            if segment.source_scene_id == scene_id:
                return segment
    return None
