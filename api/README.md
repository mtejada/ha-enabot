# EBO SE 2 Control API

A clean, documented **REST + WebSocket** API in front of the EBO engine. Your app talks only to
this service — it handles auth, validation and OpenAPI docs, and proxies to the internal engine
that holds the Enabot/Agora session.

```
your app ──HTTP(S)──▶  ebo-api (FastAPI, :8080)  ──internal──▶  ebo-engine (:8098)  ──▶  EBO SE 2
                       auth · validation · docs                 Agora RTM/RTC · RTSP        (cloud)
```

- **Interactive docs:** `http://<host>:8080/docs` (Swagger) · `/redoc` · schema at `/openapi.json`
- **Everything is env-configured** (see `.env.example`) and runs from one `docker compose`.

## Quick start

```bash
cp .env.example .env         # fill in EBO_EMAIL/PASSWORD, the two app keys, EBO_API_TOKEN, API_KEYS
docker compose up -d --build # builds the engine (amd64, ~few min) + the API
curl -s localhost:8080/health
curl -s -H "Authorization: Bearer <API_KEYS value>" localhost:8080/api/v1/robots
```

Requires an **x86_64** host (the Agora SDK is amd64-only) and the two EBO HOME app keys
(`EBO_PAYLOAD_KEY` / `EBO_SIGN_KEY`) — extract once from your own APK (`ebo/docs/GET-APP-KEYS.md`).

## Auth

Every `/api/v1/*` route needs a bearer key from `API_KEYS` (comma-separated to issue several):

```
Authorization: Bearer <key>
```

`GET /health` is open (for probes). Missing/invalid key → `401`. No keys configured → `503`
(unless `ALLOW_NO_AUTH=true`, dev only). The WebSocket accepts the key as `?token=<key>` or the
same header.

## Endpoints

Base path: **`/api/v1`**. `{id}` is the robot id from `GET /robots` (usually `ebo`).

### Meta & catalog
| method | path | notes |
|---|---|---|
| GET | `/health` | liveness, no auth → `{"status":"ok"}` |
| GET | `/api/v1/status` | `{api, version, engine_reachable, robot_count}` |
| GET | `/api/v1/account` | `{email}` of the Enabot account |
| GET | `/api/v1/voices` | `{timbres:[{name,value,provider,preview_url}], languages:[{name,value}]}` |

### Robots & state
| method | path | notes |
|---|---|---|
| GET | `/api/v1/robots` | list: `[{id,name,model,sn,mac,online,camera,state}]` |
| GET | `/api/v1/robots/{id}` | one robot (meta + full state) |
| GET | `/api/v1/robots/{id}/state` | live telemetry only (battery, wifi, docked, task, fw, …) |

### Settings (parameters)
| method | path | body |
|---|---|---|
| GET | `/api/v1/robots/{id}/settings` | current values |
| PATCH | `/api/v1/robots/{id}/settings` | any subset (below) |

```jsonc
PATCH /api/v1/robots/ebo/settings
{
  "volume": 40,               // 0..100
  "talkback_volume": 80,      // 0..100
  "speed": 30,                // 1..100  (max drive speed)
  "night_vision": "Auto",     // Auto|Day|Night
  "video_quality": "High",    // Low|Medium|High
  "image_style": "Soft",      // Standard|Vivid|Soft
  "move_mode": "Smooth",      // Smooth|Racing
  "avoid_obstacle": true,
  "sports_record": true,
  "laser": false,
  "camera": true,
  "listen": true
}
```

### Movement & power
| method | path | body / notes |
|---|---|---|
| POST | `/api/v1/robots/{id}/move` | `{direction,speed,duration}` **or** raw `{lx,ly,rx,ry,hold,buttons}` |
| POST | `/api/v1/robots/{id}/stop` | — |
| POST | `/api/v1/robots/{id}/dock` | drive to charging base |
| POST | `/api/v1/robots/{id}/wake` | wake (also refreshes video if it dozed) |
| POST | `/api/v1/robots/{id}/sleep` | let it doze |

```jsonc
// simple:
POST /api/v1/robots/ebo/move   {"direction":"forward","speed":30,"duration":1.0}
// direction ∈ forward|back|left|right|forward_left|forward_right|back_left|back_right
// raw stick vector (ly<0 = forward, rx = turn, buttons 1=dual / 0=single):
POST /api/v1/robots/ebo/move   {"ly":-30,"rx":0,"hold":1.0,"buttons":1}
```

### Actions
| method | path | body |
|---|---|---|
| POST | `/api/v1/robots/{id}/say` | `{text, timbre?, language?}` — omit voice to use the engine default |
| POST | `/api/v1/robots/{id}/patrol` | Pet Fun Patrol: `{enable,start_hour,start_minute,repeat,recording,slot_id}` |
| POST | `/api/v1/robots/{id}/commands` | **advanced** raw opcode: `{id:<int>, data:{…}}` (see `ebo/docs/SE2-COMMANDS.md`) |

```jsonc
POST /api/v1/robots/ebo/say  {"text":"Hola","timbre":"en-US-AvaMultilingualNeural","language":"es-ES"}
```

### Media
| method | path | notes |
|---|---|---|
| GET | `/api/v1/robots/{id}/snapshot` | `image/jpeg` latest still (`503` if asleep/warming) |
| GET | `/api/v1/robots/{id}/stream` | `{rtsp_url, mjpeg_url}` |
| GET | `/api/v1/robots/{id}/stream/mjpeg` | live MJPEG (`multipart/x-mixed-replace`) — drop into a browser `<img src>` |

RTSP (`rtsp://<RTSP_PUBLIC_HOST>:8554/<id>`) is the low-latency path for players/Home Assistant.

### Realtime
`WS /api/v1/robots/{id}/events` — pushes `{id, online, state}` every `EVENTS_POLL_SECONDS`.

```js
const ws = new WebSocket(`ws://host:8080/api/v1/robots/ebo/events?token=${KEY}`);
ws.onmessage = (m) => console.log(JSON.parse(m.data).state.battery);
```

## Responses & errors

Command endpoints return `{"ok":true,"robot_id":"ebo","applied":{…}}`. Errors use FastAPI's
`{"detail":"…"}` with a proper status code:

| code | when |
|---|---|
| 400 | bad command (rejected by the engine) |
| 401 | missing/invalid API key |
| 404 | unknown robot id |
| 422 | request failed validation (bad enum, out-of-range, empty move) |
| 502 | engine unreachable |
| 503 | no snapshot yet (asleep/docked/warming), or no API keys configured |

## Behavior notes (important for consumers)

- **Commands are best-effort.** A `200` means the engine accepted and dispatched the command over
  the cloud; the robot **dozes aggressively** and a stale session will ACK but ignore. If a robot
  stops reacting, call `POST …/wake` and retry, then read `…/state` to confirm.
- **Confirm with state, not just the 200.** After a `PATCH`, re-`GET …/state`; settings echo back
  from the robot with a short delay.
- **Movement safety:** `speed` and `duration`/`hold` are capped by validation; the engine also
  streams a zero-vector stop when the duration elapses (dead-man's switch). Still, only drive when
  you can see the robot (`snapshot`/`stream`).
- **Battery** drains fast under heavy driving — `POST …/dock` to recharge.

## Config (env)

See `.env.example`. Key ones: `EBO_EMAIL`/`EBO_PASSWORD`, `EBO_PAYLOAD_KEY`/`EBO_SIGN_KEY`,
`EBO_HOST`/`EBO_REGION`, `EBO_API_TOKEN` (shared engine↔api), `API_KEYS`, `CORS_ORIGINS`,
`RTSP_PUBLIC_HOST`, `EBO_TTS_TIMBRE`/`EBO_TTS_LANGUAGE`, `EVENTS_POLL_SECONDS`.

## Multiple robots

Every robot on the account is discovered automatically and appears in `GET /robots` with its own
`id`. Extra robots also get their own RTSP path/port on the engine (`8555`+). Use the `id` in every
`/robots/{id}/…` call.
