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
| Vision worker (RTSP → seg + depth + track + re-id → POST detections) | `game/vision/` | ✅ built (fake + real modes) |

**Vision stack** (2026 research, measured on a CPU/WSL2 box → ~6-8 fps):
YOLOE-26s-seg (open-vocabulary segmentation — animals **and** arbitrary props by text prompt, so
"shoe" works despite not being a COCO class) · YOLO26n-depth @512 (metric depth) · BoT-SORT
tracking · DINOv2-small re-id embeddings (384-d, kept identity across appearances). Ultralytics is
AGPL-3.0 — fine for personal use; the worker is an isolated service.

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

## Run the vision worker

It's an **optional, heavy** service (torch + models), so it only starts with the `game` profile.

```bash
cd api
# 1) set VISION_API_KEY (one of API_KEYS) in .env; keep VISION_MODE=fake to smoke-test the pipeline
docker compose --profile game up -d --build ebo-vision      # fake: synthetic dets, no models
# 2) go real once you want live detection (first run downloads the weights into the vision_weights volume):
#    set VISION_MODE=real in .env, then:
docker compose --profile game up -d ebo-vision
docker compose logs -f ebo-vision
```

Open `http://localhost:8080/game` — animals in front of the robot become bosses, props become NPC
houses. Tuning envs (see `.env.example`): `VISION_MODE`, `VISION_FPS`, `VISION_REID`, `VISION_PROPS`
(the open-vocab prompt list). The worker also keeps the camera awake so RTSP always has frames.

## Roadmap

- [x] Vision worker (`game/vision/worker.py`) — done (fake + real).
- [ ] Occlusion from segmentation masks in the frontend (worker already sends `mask`; draw the aura behind the animal).
- [ ] Optional small VLM to name/describe each boss ("orange tabby, white paws") → richer identity.
- [ ] Real 3D boss meshes (offscreen render composited with the depth map) as a visual upgrade.
- [ ] Game logic: attacks, status effects, NPC quests/dialog trees, autonomous "patrol & hunt".
