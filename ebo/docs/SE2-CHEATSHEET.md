# EBO SE 2 — cheat sheet (engine on this machine)

Everything below drives the SE 2 through the standalone **engine** running in Docker.

```bash
# --- setup: token + base URL (paste once per shell) ---
export TOK=<YOUR_API_TOKEN>        # from ~/ebo-tools/engine/data/options.json
export API=http://127.0.0.1:8098
cmd(){ curl -s -H "X-Enabot-Token: $TOK" -H 'Content-Type: application/json' \
        -d "{\"node\":\"ebo\",\"suffix\":\"$1\",\"payload\":\"$(printf %s "$2" | sed 's/"/\\"/g')\"}" \
        "$API/api/cmd"; echo; }
```

## See it
```bash
ffplay rtsp://127.0.0.1:8554/ebo                                   # live video (or VLC)
ffmpeg -rtsp_transport tcp -i rtsp://127.0.0.1:8554/ebo -frames:v 1 -update 1 shot.jpg   # one still
curl -s -H "X-Enabot-Token: $TOK" "$API/api/robots" | python3 -m json.tool               # full state
```

## Move it  (robot on the floor, clear space)
```bash
cmd move/vector '{"ly":-30,"rx":0,"hold":1.0,"buttons":1}'   # forward 1s  (ly<0 = forward)
cmd move/vector '{"ly":30,"rx":0,"hold":1.0,"buttons":1}'    # backward
cmd move/vector '{"ly":0,"rx":30,"hold":0.8,"buttons":1}'    # turn right (rx>0)
cmd move/vector '{"ly":0,"rx":-30,"hold":0.8,"buttons":1}'   # turn left
cmd move/vector '{"ly":0,"rx":0,"hold":0,"buttons":0}'       # STOP
cmd speed/set 45                                             # max drive speed 1..100
cmd dock ''                                                  # return to charging base
```

## Talk & listen
```bash
cmd say 'Hola, soy tu robot'                                 # speak (default voice Ava / es-ES)
cmd say '{"text":"Hello","timbre":"en-US-AndrewMultilingualNeural","language":"en-US"}'  # pick a voice
cmd volume/set 60                                            # speaker volume 0..100
cmd listen/set on                                            # hear the room (audio in the stream)
```
Voices: see `SE2-TTS-VOICES.md` (34 timbres, 30 languages, with preview links).

## Camera & lights
```bash
cmd laser/set on            # laser pointer (on/off)
cmd night_vision/set Auto   # Auto | Day | Night
cmd video_quality/set High  # Low | Medium | High
cmd image_style/set Soft    # Standard | Vivid | Soft
cmd camera/set on           # camera/stream on/off
```

## Power & recording
```bash
cmd wake ''                 # wake it (also forces a fresh video link if it dozed)
cmd sleep/set on            # let it doze (ZZ); wake with `cmd wake ''`
cmd sports_record/set on    # motion recording on/off
cmd avoid_obstacle/set on   # collision avoidance on/off
cmd move_mode/set Smooth    # Smooth | Racing
```

## Raw opcode (anything not wrapped above)
```bash
cmd cmd '{"id":103501,"data":{"userId":"<YOUR_ACCOUNT_ID>","text":"hi","timbre":"en-US-AvaMultilingualNeural","language":"en-US"}}'
```
Full opcode map: `SE2-COMMANDS.md`.

## AI agent (MCP)
MCP server on `http://127.0.0.1:8100/mcp` (bearer = `$TOK`). Tools: `ebo_list`, `ebo_state`,
`ebo_look`, `ebo_move`, `ebo_stop`, `ebo_say`, `ebo_laser`, `ebo_night_vision`, `ebo_listen`, `ebo_dock`.

## Manage the engine
```bash
cd ~/ebo-tools/engine
docker compose logs -f            # watch it
docker compose restart            # fresh session (fixes a dozed/stale robot)
docker compose up -d --build      # rebuild after editing the bridge code
docker compose down               # stop
```

## Gotchas
- **Dozing:** the robot naps; a stale session ACKs commands it then ignores. Fix: `cmd wake ''` or `docker compose restart`.
- **Battery** drains fast under heavy driving — `cmd dock ''` to recharge.
- `status:0` from a command means *accepted*, not necessarily *acted* (see dozing).

## Sacar el robot de la base / si no se mueve (self-service)

El SE 2 no maneja mientras está en el cargador; para salir hay que **manejar hacia adelante**
(entra de espaldas al dock, sale de frente). El engine ya se auto-recupera, así que:

1. **Mantené ↑ (adelante) ~10-15s.** Sale solo. Si está profundamente dormido, el *undock watchdog*
   reinicia el bridge automáticamente (~15-20s, el video parpadea) y al seguir apretando ↑, sale.
2. **Si igual no sale:** sesión nueva a mano y volvé a manejar:
   ```bash
   cd ~/projects/ha-enabot/api && docker compose restart ebo-engine   # ~15s
   ```
   Esperá que reconecte y mantené ↑.
3. **Recargar:** botón **Dock** (o `cmd dock ''`) — vuelve a la base solo.

Notas: sólo los comandos de **movimiento** arman los watchdogs (el keepalive de visión no interfiere).
`docked=true/charging=true` en `/api/v1/robots/ebo/state` = está en la base.
