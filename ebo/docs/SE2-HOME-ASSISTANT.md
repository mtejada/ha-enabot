# EBO SE 2 → Home Assistant

The engine we're running already **bundles the companion HA integration**. Wiring it into Home
Assistant gives you a real HA **device + live camera + entities** (battery, wifi, laser, night
vision, drive speed, volume, dock, sleep, …) you can put on dashboards and use in automations —
no MQTT, no HACS.

> There is **no Home Assistant on this machine** right now (checked: no container, nothing on
> :8123). Do this on the box where HA actually runs, or point the engine's mount at that box's
> config share.

## Which path applies to you

- **HA OS / Supervised** (can run add-ons): you'd normally install the repo as an **add-on**
  (`Settings → Add-ons → ⋮ → Repositories → https://github.com/Playcolors-co/ha-enabot`). But the
  add-on image is **amd64-only** (the Agora SDK), so on a Raspberry Pi HA OS it won't run — use the
  standalone engine below on a small x86_64 box and add the integration **manually**.
- **HA Container / Core** (no Supervisor): use the standalone engine (what we're already running) +
  the **manual** integration step. This is the path below.

## 1) Let the engine install the integration into your HA config

Edit `~/ebo-tools/engine/docker-compose.yml` and mount your Home Assistant config directory, so the
engine drops the integration into `custom_components/ebo` for you:

```yaml
    volumes:
      - ./data:/data
      - /path/to/your/homeassistant/config:/homeassistant   # <-- add this line
```

`docker compose up -d`, then **restart Home Assistant once** so it loads the new component.
(If you can't mount it, copy `ebo/ha_integration/custom_components/ebo` into your HA
`config/custom_components/ebo` by hand instead, then restart HA.)

## 2) Add the integration

**Settings → Devices & Services → + Add Integration → “EBO”.** With no Supervisor it opens the
**manual** step — fill in, from the machine running the engine:

| field | value |
|---|---|
| RTSP URL | `rtsp://<engine-ip>:8554/ebo` |
| API URL | `http://<engine-ip>:8098` |
| API token | `<YOUR_API_TOKEN>`  (the `api_token` in `data/options.json`) |
| name | e.g. `EBO SE 2` (serial/MAC/model optional) |

`<engine-ip>` = this machine's LAN IP as HA sees it. Submit → you get the robot as a device with a
**live camera** + native entities.

> WSL note: this engine runs inside WSL2 (NAT). For HA on another host to reach `:8554`/`:8098`,
> forward those ports from Windows to WSL (`netsh interface portproxy add v4tov4 …`) or run the
> engine on a box HA can reach directly. Same-host HA (in WSL) can use the WSL IP.

## 3) Extra robots

One integration entry per robot. Additional robots stream on `8555/8556/8557` (RTSP) — add another
entry pointing at the next port.

## What you get in HA

- **Camera**: live WebRTC/stream via HA's `stream`/go2rtc.
- **Controls** as entities: camera on/off, laser, night vision, video quality, image style, drive
  speed, volume, driving mode, obstacle avoidance, dock button, sleep switch, wake button.
- **Sensors**: battery, wifi signal, charging, docked, SD present, firmware.
- **TTS**: the `say` command is exposed; the SE 2 voice defaults are set by the engine
  (`EBO_TTS_TIMBRE` / `EBO_TTS_LANGUAGE` in the compose) — see `SE2-TTS-VOICES.md`.

SE 2 specifics (eyes not present; rotate-to-angle / Air 2 patrol not applicable) are in
`SE2-COMMANDS.md`.
