# EBO Boss Hunt — AR game layer

Turn the EBO SE 2's live camera into a game world: **animals become bosses** (with persistent HP /
status), **objects become NPC houses** (proximity dialogs), rendered as an overlay that **respects
depth** (nearer = bigger, drawn on top). Reuses the control API — it does **not** touch the robot's
control path.

```
ebo-engine ─RTSP:8554→ ebo-vision (YOLO-seg + depth + tracking + re-id)
                              │  POST /api/v1/robots/ebo/detections
                              ▼
                           ebo-api ──────────────► game/web  (served at /game)
                     (detections + persistent      canvas over the live video:
                      game entities: HP, status)   bosses / NPC houses / dialogs
                                     ▲  WS /detections/stream · GET /entities
```

## Pieces

| piece | where | status |
|---|---|---|
| Game API (detections ingest, persistent entities, damage, WS) | `api/app/game.py` | ✅ done |
| Game frontend (canvas over video, depth-scaled bosses/NPCs, click-to-attack, dialogs) | `game/web/index.html` → served at **`/game`** | ✅ skeleton |
| Vision worker (RTSP → YOLO-seg + depth + track + re-id embeddings → POST detections) | `game/vision/` | ⏳ model stack being chosen (2026 research) |

## Run

The API + engine already run from `../api`. Open the game at **`http://localhost:8080/game`**
(⚙ → paste API base + your `API_KEYS` key). Until the vision worker runs you can drive it with
fake detections:

```bash
KEY=<your API key>; B=http://localhost:8080/api/v1
curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"ts":0,"source_w":1280,"source_h":720,"detections":[
        {"label":"cat","conf":0.9,"bbox":[0.4,0.3,0.2,0.35],"depth":0.3,"track_id":1},
        {"label":"shoe","conf":0.7,"bbox":[0.08,0.62,0.12,0.1],"depth":0.35,"track_id":2}]}' \
  $B/robots/ebo/detections
```

## The detection contract (what the worker POSTs)

`POST /api/v1/robots/{id}/detections` — one frame:

```jsonc
{
  "ts": 1788800000.0,           // epoch seconds
  "source_w": 1280, "source_h": 720,
  "detections": [{
    "label": "cat",             // raw model class
    "role": "boss",             // boss | npc_house | prop  (API fills it if omitted)
    "conf": 0.92,
    "bbox": [0.40,0.30,0.20,0.35],   // x,y,w,h NORMALIZED 0..1 (top-left origin)
    "depth": 0.35,              // 0=near .. 1=far (relative), or meters if metric
    "mask": [[[x,y],...]],      // optional polygon(s), normalized — for occlusion
    "track_id": 1,              // short-term tracker id (ByteTrack/BoTSORT)
    "embedding": [ ... ]        // optional re-id vector (worker→API only; used to keep identity)
  }]
}
```

The API resolves each detection to a **persistent entity** (a specific boss/NPC): same `track_id`
within a session, and — when the worker sends an `embedding` — matched across sessions by cosine
similarity, so a boss keeps its HP / status when it wanders off and comes back.

Consumers:
- `WS /api/v1/robots/{id}/detections/stream` — live `{frame, entities}` at N Hz (the game uses this).
- `GET /api/v1/robots/{id}/entities` — persistent entities with HP/status/name.
- `PATCH /api/v1/robots/{id}/entities/{eid}` · `POST …/{eid}/damage?amount=N` — game actions.

## Depth handling

The overlay scales art by `depth` (near→bigger) and draws far→near so nearer bosses sit on top.
When the worker sends per-detection **masks**, the frontend will use them for true occlusion (aura /
NPC art goes *behind* the animal) — the "3D boss dropped into the room" look.

## Roadmap (after the model research lands)

- [ ] `game/vision/worker.py`: RTSP in → detect+segment animals + open-vocab objects (e.g. "shoe")
      → monocular depth → tracker + re-id embeddings → POST detections. Docker service in the compose.
- [ ] Occlusion from segmentation masks (send `mask`, cut the aura behind the animal).
- [ ] Optional small VLM to name/describe each boss ("orange tabby, white paws") → richer identity.
- [ ] Real 3D boss meshes (offscreen render composited with the depth map) as a visual upgrade.
- [ ] Game logic: attacks, status effects, NPC quests/dialog trees, autonomous "patrol & hunt".
