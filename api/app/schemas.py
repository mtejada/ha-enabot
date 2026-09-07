"""Request/response models. Enums here become the documented, validated value sets in OpenAPI."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- enums (validated value sets) ---
class NightVision(str, Enum):
    Auto = "Auto"
    Day = "Day"
    Night = "Night"


class VideoQuality(str, Enum):
    Low = "Low"
    Medium = "Medium"
    High = "High"


class ImageStyle(str, Enum):
    Standard = "Standard"
    Vivid = "Vivid"
    Soft = "Soft"


class MoveMode(str, Enum):
    Smooth = "Smooth"
    Racing = "Racing"


class Direction(str, Enum):
    forward = "forward"
    back = "back"
    left = "left"
    right = "right"
    forward_left = "forward_left"
    forward_right = "forward_right"
    back_left = "back_left"
    back_right = "back_right"


# --- robot / state ---
class RobotState(BaseModel):
    """Live telemetry. Extra fields the firmware reports pass through unchanged."""
    model_config = ConfigDict(extra="allow")
    battery: int | None = None
    charging: str | None = None
    wifi: int | None = None
    docked: str | None = None
    task: str | None = None
    laser: str | None = None
    listen: str | None = None
    volume: int | None = None
    speed: int | None = None
    night_vision: str | None = None
    video_quality: str | None = None
    move_mode: str | None = None
    avoid_obstacle: str | None = None
    sports_record: str | None = None
    fw_ipc: str | None = None
    fw_mcu: str | None = None
    ip: str | None = None


class Robot(BaseModel):
    id: str = Field(description="stable robot id (the engine node name)")
    name: str | None = None
    model: str | None = None
    sn: str | None = None
    mac: str | None = None
    online: bool = False
    camera: str | None = None
    state: RobotState = RobotState()

    @classmethod
    def from_engine(cls, rb: dict[str, Any]) -> "Robot":
        return cls(
            id=rb.get("node", ""),
            name=rb.get("name"),
            model=rb.get("model"),
            sn=rb.get("sn"),
            mac=rb.get("mac"),
            online=bool(rb.get("online")),
            camera=rb.get("camera"),
            state=RobotState(**(rb.get("state") or {})),
        )


# --- settings (PATCH) ---
class SettingsPatch(BaseModel):
    """Every field optional — send only what you want to change."""
    model_config = ConfigDict(extra="forbid")
    volume: int | None = Field(default=None, ge=0, le=100)
    talkback_volume: int | None = Field(default=None, ge=0, le=100)
    speed: int | None = Field(default=None, ge=1, le=100, description="max drive speed")
    night_vision: NightVision | None = None
    video_quality: VideoQuality | None = None
    image_style: ImageStyle | None = None
    move_mode: MoveMode | None = None
    avoid_obstacle: bool | None = None
    sports_record: bool | None = None
    laser: bool | None = None
    camera: bool | None = None
    listen: bool | None = None


# --- movement ---
class MoveRequest(BaseModel):
    """Two ways to drive. EITHER a simple direction+speed+duration, OR a raw stick vector.
    `ly` is forward/back (negative = forward), `rx` is turn. buttons: 1 dual-stick, 0 single."""
    model_config = ConfigDict(extra="forbid")
    direction: Direction | None = None
    speed: int = Field(default=25, ge=1, le=100)
    duration: float = Field(default=1.0, gt=0, le=10, description="seconds to drive (capped)")
    # raw vector (used when `direction` is omitted)
    lx: int | None = Field(default=None, ge=-100, le=100)
    ly: int | None = Field(default=None, ge=-100, le=100)
    rx: int | None = Field(default=None, ge=-100, le=100)
    ry: int | None = Field(default=None, ge=-100, le=100)
    hold: float | None = Field(default=None, gt=0, le=10)
    buttons: int = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def _need_something(self) -> "MoveRequest":
        if self.direction is None and not any(
            v is not None for v in (self.lx, self.ly, self.rx, self.ry)
        ):
            raise ValueError("provide `direction` or at least one of lx/ly/rx/ry")
        return self

    def to_vector(self) -> dict[str, Any]:
        _D = {
            Direction.forward: (-1, 0), Direction.back: (1, 0),
            Direction.left: (0, -1), Direction.right: (0, 1),
            Direction.forward_left: (-1, -1), Direction.forward_right: (-1, 1),
            Direction.back_left: (1, -1), Direction.back_right: (1, 1),
        }
        if self.direction is not None:
            uy, ux = _D[self.direction]
            mag = (uy * uy + ux * ux) ** 0.5 or 1.0
            return {"lx": 0, "ly": round(uy / mag * self.speed),
                    "rx": round(ux / mag * self.speed), "ry": 0,
                    "hold": self.duration, "buttons": self.buttons}
        return {"lx": self.lx or 0, "ly": self.ly or 0, "rx": self.rx or 0,
                "ry": self.ry or 0, "hold": self.hold or self.duration, "buttons": self.buttons}


# --- actions ---
class SayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    timbre: str | None = Field(default=None, description="voice id from GET /voices; engine default if omitted")
    language: str | None = Field(default=None, description="language id from GET /voices")


class PatrolRequest(BaseModel):
    """Pet Fun Patrol — a scheduled laser-play session (the SE 2's 'patrol')."""
    model_config = ConfigDict(extra="forbid")
    enable: bool = True
    start_hour: int = Field(ge=0, le=23)
    start_minute: int = Field(ge=0, le=59)
    repeat: int = Field(default=127, ge=0, le=127, description="day-of-week bitmask")
    recording: bool = True
    slot_id: int = Field(default=1, ge=0)


class RawCommand(BaseModel):
    """Escape hatch — send any RTM opcode. Advanced; see docs/SE2-COMMANDS.md for opcodes."""
    model_config = ConfigDict(extra="forbid")
    id: int = Field(description="RTM opcode, e.g. 103501")
    data: dict[str, Any] | None = None


# --- responses ---
class CommandResult(BaseModel):
    ok: bool = True
    robot_id: str
    detail: str | None = None
    applied: dict[str, Any] | None = None


class Voice(BaseModel):
    name: str | None = None
    value: str
    provider: str | None = None
    preview_url: str | None = None


class Language(BaseModel):
    name: str | None = None
    value: str


class Voices(BaseModel):
    timbres: list[Voice]
    languages: list[Language]


class StreamInfo(BaseModel):
    rtsp_url: str
    mjpeg_url: str


class Status(BaseModel):
    api: str = "ok"
    version: str
    engine_reachable: bool
    robot_count: int


# ============================================================================
#  Vision / game layer — the ebo-vision worker POSTs detections here; the game
#  frontend reads detections (live) + entities (persistent state) to render an
#  AR world (animals = bosses, objects = NPC houses) over the video.
# ============================================================================
class Detection(BaseModel):
    """One detection in a frame. Coordinates are normalized 0..1 (top-left origin) so the frontend
    scales them to whatever size it draws the video at."""
    model_config = ConfigDict(extra="ignore")
    label: str                                  # raw model class, e.g. "cat", "shoe"
    role: str = "prop"                           # game role: boss | npc_house | prop
    conf: float = 1.0
    bbox: list[float]                            # [x, y, w, h] normalized 0..1
    depth: float | None = None                   # 0 = near .. 1 = far (relative), or meters if metric
    mask: list[list[float]] | None = None        # optional polygon(s): [[x,y],...] normalized (occlusion)
    track_id: int | None = None                  # short-term tracker id (ByteTrack/BoTSORT)
    entity_id: str | None = None                 # stable game id (API assigns via track/re-id)
    embedding: list[float] | None = Field(default=None, exclude=True)  # re-id vector (worker→API only)


class DetectionsFrame(BaseModel):
    ts: float = 0.0
    source_w: int = 0
    source_h: int = 0
    detections: list[Detection] = []


class Entity(BaseModel):
    """A persistent game entity resolved from detections (a specific boss/NPC). State survives across
    frames so a boss keeps its HP / status even as it moves or briefly leaves the view."""
    id: str
    role: str                                    # boss | npc_house | prop
    label: str
    name: str | None = None                      # display name (VLM/derived); e.g. "Sir Whiskers"
    hp: int = 100
    max_hp: int = 100
    status: list[str] = []                        # e.g. ["enraged", "poisoned"]
    attributes: dict[str, Any] = {}               # freeform: color, description, dialog lines…
    last_seen: float = 0.0
    bbox: list[float] | None = None               # last known (for rendering when between frames)
    depth: float | None = None


class EntityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hp: int | None = Field(default=None, ge=0)
    name: str | None = None
    status: list[str] | None = None
    attributes: dict[str, Any] | None = None
