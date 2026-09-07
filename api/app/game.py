"""Vision / game layer.

The `ebo-vision` worker runs YOLO(+seg) + depth (+ tracking + re-id embeddings) on the robot's RTSP
stream and POSTs detections here. The API resolves each detection to a PERSISTENT game entity — a
specific boss/NPC that keeps its state (HP, status, name) across frames and re-appearances — using
the short-term track id and, when provided, a re-id embedding matched against a per-robot gallery.

The game frontend then:
  - streams live detections   (WS /detections/stream) to draw boxes/masks with depth, and
  - reads persistent entities (GET /entities) for HP bars, names, status effects,
  - and mutates state (PATCH /entities/{id}, POST /entities/{id}/damage) as you play.

State is in-memory (single-process). Fine for one game; swap for a store if you scale out.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from .config import Settings, get_settings
from .schemas import Detection, DetectionsFrame, Entity, EntityPatch
from .security import require_api_key

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

# --- game rules -------------------------------------------------------------
# Animals → bosses. With prompt-free detection labels are arbitrary, so match by keyword.
ANIMALS = {"cat", "dog", "bird", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
ANIMAL_WORDS = ("cat", "kitten", "dog", "puppy", "bird", "horse", "sheep", "cow", "elephant", "bear",
                "zebra", "giraffe", "animal", "pet", "rabbit", "hamster", "fish", "turtle", "lizard",
                "snake", "mouse", "rat", "fox", "deer", "lion", "tiger", "monkey", "pig", "goat",
                "duck", "chicken", "parrot", "hedgehog", "ferret", "guinea pig")
DEFAULT_HP = {"boss": 100, "npc_house": 1, "prop": 1}
REID_THRESHOLD = 0.82          # cosine similarity to call two crops "the same individual"
STALE_ENTITY_SECS = 3600       # forget an entity unseen this long (bound memory)
_BOSS_TITLES = ["Sir", "Lord", "Lady", "Dread", "Ancient", "Mad", "Grand", "Shadow", "Iron"]
_BOSS_NAMES = ["Whiskers", "Mittens", "Fang", "Bacon", "Nugget", "Pixel", "Biscuit", "Loki",
               "Zoltar", "Mochi", "Gizmo", "Tuna"]


def role_for(label: str) -> str:
    l = label.lower()
    return "boss" if any(w in l for w in ANIMAL_WORDS) else "npc_house"


def _boss_name(label: str) -> str:
    return f"{random.choice(_BOSS_TITLES)} {random.choice(_BOSS_NAMES)}"


# --- per-robot state --------------------------------------------------------
_frames: dict[str, DetectionsFrame] = {}                 # latest detections
_entities: dict[str, dict[str, Entity]] = {}             # robot -> entity_id -> Entity
_gallery: dict[str, dict[str, list[float]]] = {}         # robot -> entity_id -> re-id embedding
_track_map: dict[str, dict[str, tuple[str, float]]] = {} # robot -> "label:track" -> (entity_id, ts)
_counter: dict[str, int] = {}


def _cos(a: list[float], b: list[float]) -> float:
    s = da = db = 0.0
    for x, y in zip(a, b):
        s += x * y; da += x * x; db += y * y
    return s / (math.sqrt(da) * math.sqrt(db) + 1e-9)


def _new_id(robot: str, label: str) -> str:
    _counter[robot] = _counter.get(robot, 0) + 1
    return f"{label}-{_counter[robot]}"


def _resolve(robot: str, det: Detection, now: float) -> str:
    """Map a detection to a stable entity id: track id within a session, embedding across sessions."""
    ents = _entities.setdefault(robot, {})
    tmap = _track_map.setdefault(robot, {})
    gal = _gallery.setdefault(robot, {})
    # 1) same short-term track we saw very recently → same entity
    if det.track_id is not None:
        key = f"{det.label}:{det.track_id}"
        hit = tmap.get(key)
        if hit and now - hit[1] < 5:
            tmap[key] = (hit[0], now)
            return hit[0]
    # 2) re-id: match the embedding against this robot's gallery (same label only)
    eid = None
    if det.embedding:
        best, bs = None, REID_THRESHOLD
        for cid, emb in gal.items():
            if ents.get(cid) and ents[cid].label == det.label:
                c = _cos(det.embedding, emb)
                if c > bs:
                    best, bs = cid, c
        eid = best
    # 3) otherwise a brand-new entity
    if eid is None:
        eid = _new_id(robot, det.label)
        role = role_for(det.label)
        ents[eid] = Entity(id=eid, role=role, label=det.label,
                           name=_boss_name(det.label) if role == "boss" else None,
                           hp=DEFAULT_HP.get(role, 1), max_hp=DEFAULT_HP.get(role, 1))
        if det.embedding:
            gal[eid] = det.embedding
    if det.track_id is not None:
        tmap[f"{det.label}:{det.track_id}"] = (eid, now)
    return eid


def _prune(robot: str, now: float) -> None:
    ents = _entities.get(robot, {})
    for cid in [c for c, e in ents.items() if now - e.last_seen > STALE_ENTITY_SECS]:
        ents.pop(cid, None); _gallery.get(robot, {}).pop(cid, None)


def _robot(robot_id: str) -> str:
    return robot_id or "ebo"


# --- ingest (worker → API) --------------------------------------------------
@router.post("/robots/{robot_id}/detections", tags=["vision"],
             summary="Ingest a frame of detections (ebo-vision worker)")
async def post_detections(robot_id: str, frame: DetectionsFrame):
    robot = _robot(robot_id)
    now = frame.ts or time.time()
    ents = _entities.setdefault(robot, {})
    for det in frame.detections:
        if not det.role or det.role == "prop":
            det.role = role_for(det.label)
        eid = _resolve(robot, det, now)
        det.entity_id = eid
        e = ents[eid]
        e.last_seen = now; e.bbox = det.bbox; e.depth = det.depth
        if e.role != det.role:
            e.role = det.role
    _prune(robot, now)
    _frames[robot] = frame
    return {"ok": True, "detections": len(frame.detections),
            "entities": [ents[d.entity_id].model_dump() for d in frame.detections if d.entity_id]}


# --- read (game → API) ------------------------------------------------------
@router.get("/robots/{robot_id}/detections", tags=["vision"], response_model=DetectionsFrame,
            summary="Latest detections frame")
async def get_detections(robot_id: str):
    return _frames.get(_robot(robot_id), DetectionsFrame())


@router.get("/robots/{robot_id}/entities", tags=["vision"], response_model=list[Entity],
            summary="Persistent game entities (bosses/NPCs) with state")
async def list_entities(robot_id: str, fresh: float | None = Query(default=None,
                        description="only entities seen within this many seconds")):
    ents = list(_entities.get(_robot(robot_id), {}).values())
    if fresh is not None:
        now = time.time(); ents = [e for e in ents if now - e.last_seen <= fresh]
    return ents


@router.get("/robots/{robot_id}/entities/{eid}", tags=["vision"], response_model=Entity)
async def get_entity(robot_id: str, eid: str):
    e = _entities.get(_robot(robot_id), {}).get(eid)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entity not found")
    return e


@router.patch("/robots/{robot_id}/entities/{eid}", tags=["vision"], response_model=Entity,
              summary="Update entity state (hp/name/status/attributes)")
async def patch_entity(robot_id: str, eid: str, body: EntityPatch):
    e = _entities.get(_robot(robot_id), {}).get(eid)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entity not found")
    d = body.model_dump(exclude_none=True)
    if "hp" in d:
        e.hp = max(0, min(d["hp"], e.max_hp))
    if "name" in d:
        e.name = d["name"]
    if "status" in d:
        e.status = d["status"]
    if "attributes" in d:
        e.attributes.update(d["attributes"])
    return e


@router.post("/robots/{robot_id}/entities/{eid}/damage", tags=["vision"], response_model=Entity,
             summary="Deal damage to a boss (game action)")
async def damage_entity(robot_id: str, eid: str, amount: int = Query(default=10, ge=0)):
    e = _entities.get(_robot(robot_id), {}).get(eid)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entity not found")
    e.hp = max(0, e.hp - amount)
    if e.hp == 0 and "defeated" not in e.status:
        e.status = [*e.status, "defeated"]
    return e


# --- realtime (game ← API) --------------------------------------------------
@router.websocket("/robots/{robot_id}/detections/stream")
async def detections_stream(ws: WebSocket, robot_id: str, token: str | None = Query(default=None),
                            hz: float = Query(default=10.0, ge=1, le=30)):
    s: Settings = get_settings()
    keys = s.api_key_set
    supplied = token or (ws.headers.get("authorization", "").removeprefix("Bearer ").strip() or None)
    if keys and supplied not in keys and not s.allow_no_auth:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION); return
    await ws.accept()
    robot = _robot(robot_id)
    try:
        while True:
            f = _frames.get(robot)
            if f is not None:
                ents = _entities.get(robot, {})
                await ws.send_json({
                    "frame": f.model_dump(),
                    "entities": [ents[d.entity_id].model_dump()
                                 for d in f.detections if d.entity_id and d.entity_id in ents],
                })
            await asyncio.sleep(1.0 / hz)
    except WebSocketDisconnect:
        return
