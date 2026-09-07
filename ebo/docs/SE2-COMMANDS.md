# EBO SE 2 — control & view via the cloud engine (verified)

Notes from getting an **EBO SE 2** working through this project's engine (the same code as the
add-on, run standalone). The SE 2 is **not** in the add-on's officially verified list, but it turns
out to ride the **same Agora cloud + RTM opcodes** as the EBO Air 2. This file records exactly what
was tested against a real SE 2 and what came back from the robot.

> Unofficial, reverse-engineered, uses your own account. Opcodes are the Air 2 set; the SE 2
> accepts almost all of them. Where it differs, it's called out below.

## The device under test

```
machine_version : "ebo se 2"
sn              : <device-serial>
fw (ipc)        : v1.0.52-0-gc9de5c1 build20260721
fw (mcu)        : v0.0.9-1-g3a1396f
video           : 2304x1296 (2K) H.265 → engine re-encodes to 720p H.264/RTSP
transport       : Agora RTC (video/audio) + RTM (control), channel se2_us_…
```

The cloud `POST /api/v1/ebox/robots/session` returns a full Agora session for the SE 2 (rtm+rtc
tokens), so the engine attaches with no SE-specific code. It also carries `tutk_info` (the SE
family's local P2P), but the cloud path is enough and is what the engine uses.

## Three ways to drive it

The engine exposes a token-guarded data API (default `:8098`). `TOK` = the `api_token` from
`data/options.json`.

**1. Read state**
```bash
curl -s -H "X-Enabot-Token: $TOK" http://ENGINE:8098/api/robots | python3 -m json.tool
```

**2. Send a command** — `POST /api/cmd {node, suffix, payload}`
```bash
curl -s -H "X-Enabot-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"node":"ebo","suffix":"laser/set","payload":"on"}' http://ENGINE:8098/api/cmd
```
`suffix` is one of the high-level commands below, or `move/vector`, or `cmd` (raw opcode).

**3. Raw opcode escape hatch** — for anything not wrapped as a suffix:
```bash
curl ... -d '{"node":"ebo","suffix":"cmd","payload":"{\"id\":103009,\"data\":{\"moveSpeed\":40}}"}' \
  http://ENGINE:8098/api/cmd
```

**View:** `rtsp://ENGINE:8554/ebo` (any player / HA camera). One frame:
`ffmpeg -rtsp_transport tcp -i rtsp://ENGINE:8554/ebo -frames:v 1 -update 1 out.jpg`.

**AI agent:** MCP server on `:8100` (bearer = `api_token`): `ebo_look`, `ebo_move`, `ebo_say`,
`ebo_laser`, `ebo_night_vision`, `ebo_listen`, `ebo_dock`, `ebo_stop`.

## Verified on the SE 2 — non-locomotion

Each was fired and the **robot echoed a matching report** (proof it acted). `suffix` = the
`/api/cmd` suffix; `send`/`echo` = the RTM opcodes out/back.

| command | suffix | payload | send→echo | result |
|---|---|---|---|---|
| Laser pointer | `laser/set` | `on` / `off` | 103051 → **103052** `{laser}` | ✅ works |
| Day/Night vision | `night_vision/set` | `Auto`/`Day`/`Night` | 102035 → **102036** `{shootMode}` | ✅ works |
| Video quality | `video_quality/set` | `Low`/`Medium`/`High` | 102055 → **102056** `{videoQuality}` | ✅ works |
| Image style | `image_style/set` | `Standard`/`Vivid`/`Soft` | 102057 → **102058** `{imageStyle}` | ✅ works |
| Playback volume | `volume/set` | `0`..`100` | 102023 → **102024** `{playbackVolume}` | ✅ works |
| Talkback volume | `talkback_volume/set` | `0`..`100` | 102031 → **102032** `{talkbackVolume}` | ✅ works |
| Max drive speed | `speed/set` | `1`..`100` | 103009 → **103010** `{moveSpeed}` | ✅ works (setting only, no move) |
| Driving mode | `move_mode/set` | `Smooth`/`Racing` | 103011 → **103012** `{moveMode}` | ✅ works |
| Collision avoidance | `avoid_obstacle/set` | `on`/`off` | 103045 → **103046** `{avoidobstacle}` | ✅ works |
| Motion recording | `sports_record/set` | `on`/`off` | 101049 → **101050** `{sportsRecord}` | ✅ works |
| Microphone (listen) | `listen/set` | `on`/`off` | 102001 → **102002** `{open}` | ✅ works (hear the room) |
| Wake | `wake` | `` | 101047 → **101048** `{isSleeping:false}` | ✅ works |
| Camera on/off | `camera/set` | `on`/`off` | — | ✅ works (video pipeline live) |
| Telemetry/state | *(GET /api/robots)* | — | 101004 info, 101026 telem, 101028 settings | ✅ works |

Sleep (`sleep/set on`, opcode 101047 `{isSleeping:true}`) is expected to work too but wasn't fired
during the sweep because it releases the Agora session (the robot dozes) — reversible with `wake`.

## Text-to-speech — FIXED (needs a voice)

The SE 2's `say` (opcode **103501**) needs **two extra fields** the Air 2 didn't: a valid
`timbre` and `language`. With them missing the robot ACKs `status:0` but stays **silent**; with
them it speaks. Valid values come from the cloud voice list — see **`docs/SE2-TTS-VOICES.md`**
(34 voices, 30 languages, with preview links). The engine now sends them automatically:

```
# default voice (EBO_TTS_TIMBRE / EBO_TTS_LANGUAGE):
{"node":"ebo","suffix":"say","payload":"Hola, ya puedo hablar"}
# pick a voice per message (JSON payload):
{"node":"ebo","suffix":"say","payload":"{\"text\":\"Hello\",\"timbre\":\"en-US-AndrewMultilingualNeural\",\"language\":\"en-US\"}"}
```

Gotchas learned the hard way: **the robot must be awake and the RTM session fresh** (it dozes
aggressively — a stale session ACKs commands but the robot ignores them; `wake` forces an RTC
rejoin), and **the volume must be up**. `status:0` means *accepted*, not *spoken*.

## Does NOT work on the SE 2

| command | suffix | what happened | note |
|---|---|---|---|
| Eyes / emoji | `eyes/set` | 104057 → **no echo** | the SE 2 has **no eye display** (different form factor from the Air 2). Not applicable. |

## Locomotion — CONFIRMED (drives over Agora RTM)

Driving works on the SE 2 over the **same path** as everything else: opcode **101007
`{lx,ly,rx,ry,buttons}`** published as an Agora RTM peer message to the robot's `robot_rtm_uid`.
No TUTK needed. (The app's `Se2LiveModel` logs this as "sendMoveRDTdata", but that tag is stale
copy-paste — the actual send, `DeviceSe2WrapInfo.P()`, routes through the Agora object, and the
payload builder `nb.b.t()` produces exactly `101007 {lx,ly,rx,ry,buttons}`.)

Verified: a **turn** visibly rotated the robot; a **backward** drive shifted the camera view by
~5% of pixels. Forward is delivered identically — a low visual delta just means it faced a
low-texture surface. The engine streams the vector at 10 Hz for `hold` seconds, then a zero frame
to stop (dead-man's switch).

| command | suffix | payload | opcode | status |
|---|---|---|---|---|
| Drive (vector) | `move/vector` | `{"ly":-30,"rx":0,"hold":1.0,"buttons":1}` (fwd ~1s) | 101007 | ✅ works |
| Turn in place | `move/vector` | `{"ly":0,"rx":30,"hold":0.8,"buttons":1}` | 101007 | ✅ works |
| Stop | `move/vector` | `{"ly":0,"rx":0,"hold":0,"buttons":0}` | 101007 | ✅ works |

`ly` −100..100 (**forward = negative**), `rx` −100..100 (turn), `hold` = seconds to drive,
`buttons` 1 = dual-stick (independent throttle + continuous turn), 0 = single-stick (vector is a
heading). Max speed is capped by `speed/set` (see above).

### Return to base — CONFIRMED

| command | suffix | payload | opcode | status |
|---|---|---|---|---|
| Return to base | `dock` | `` | 103043 | ✅ works |

Tested: `dock` echoed `103044 {startUp:true}`, `task` went `idle→moving→charging`, the camera view
changed massively as it crossed the room, and it ended `docked=true, charging=true`. Docking also
releases the Agora session so the robot can sleep on the base (like closing the app).

### Sleep — CONFIRMED

`sleep/set on` (101047 `{isSleeping:true}`) → robot dozes; `wake` → `{isSleeping:false}`. ✅

### Air 2 locomotion that does NOT apply to the SE 2

| command | opcode | result |
|---|---|---|
| Rotate to exact angle | 103001 | ✗ not an SE 2 command (absent from the SE 2 app builders; turn with a `move/vector` `rx` instead) |
| Preset motions ("tricks") | 103005 | valid opcode but the SE 2 returns no motion list (103021 silent) and `moveId` 1/2 no-op — effectively unsupported |
| Air 2-style patrol / routes | 103061 / 104001 | ✗ 104001 (route list) gets no reply; the SE 2 has its **own** route system (app `Ese2*Route*` classes, different opcodes — not yet mapped) |
| AI subject tracking | 103049 | not tested — interactive (you tap the subject in the app's live video) |

## SE 2 patrol = "Pet Fun Patrol" (teasing pets)

The SE 2 has **no Air 2-style recorded drive-routes**. Its patrol feature is **Pet Fun Patrol** —
a *scheduled* session where it drives around, flashes the laser to play with a pet, and optionally
records. It's opcode **`104017`** with `Ese2TeasingPetsData`:

| field | meaning |
|---|---|
| `id` | schedule slot id (int) |
| `enable` | 1 on / 0 off |
| `startHour` | 0–23 |
| `startMinute` | 0–59 |
| `repeat` | day-of-week bitmask |
| `recording` | 1 record clips / 0 not |

```bash
# schedule a Pet Fun Patrol at 18:30 with recording on:
cmd cmd '{"id":104017,"data":{"id":1,"enable":1,"startHour":18,"startMinute":30,"repeat":127,"recording":1}}'
```

Not tested live (it schedules a future run and the robot was on the base). Field order confirmed
from the app's `Ese2TeasingPetsData` class; `repeat`'s exact bit layout wasn't reversed — set/read
it once in the EBO HOME app and mirror the value.

## Open items to go past the PoC

- [x] ~~Fix TTS for the SE 2~~ — done (needs `timbre`+`language`; see above and `SE2-TTS-VOICES.md`).
- [x] ~~Test locomotion~~ — drive/turn/stop/dock/sleep confirmed; rotate-to-angle, preset motions and Air 2 patrol don't apply.
- [x] ~~Map the SE 2's route/patrol system~~ — it's "Pet Fun Patrol" (teasing pets, `104017`); see above.
- [ ] Confirm SD-card / cloud-recording opcodes (SE 2 has 24/7 + event recording).
- [ ] AI subject tracking (103049) — interactive; needs the app's tap-to-select flow reproduced.
- [ ] Optional: run the companion integration inside Home Assistant for dashboards/automations.

## Note: `/api/snapshot`

Serves the **last decoded frame** (cached). Returns 404 only on a cold cache (stream still warming)
or when the robot is asleep/docked (camera off). For a guaranteed still, grab from RTSP:
`ffmpeg -rtsp_transport tcp -i rtsp://ENGINE:8554/ebo -frames:v 1 -update 1 out.jpg`.
