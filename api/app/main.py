"""EBO SE 2 Control API — a clean, documented REST layer over the EBO engine.

Your app talks only to this service (auth + validation + OpenAPI); this service proxies to the
internal engine that holds the Agora session. Interactive docs at /docs, schema at /openapi.json.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import (APIRouter, Depends, FastAPI, Query, Request, Response,
                     WebSocket, WebSocketDisconnect, status)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from .config import Settings, get_settings
from .engine import EngineClient
from .schemas import (CommandResult, MoveRequest, PatrolRequest, RawCommand, Robot,
                      RobotState, SayRequest, SettingsPatch, Status, StreamInfo, Voices)
from .security import require_api_key

_VOICES = json.loads((Path(__file__).parent / "voices.json").read_text(encoding="utf-8"))
_SETTINGS_KEYS = ("volume", "talkback_volume", "speed", "night_vision", "video_quality",
                  "image_style", "move_mode", "avoid_obstacle", "sports_record",
                  "laser", "camera", "listen")


def _onoff(b: bool) -> str:
    return "on" if b else "off"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.http = httpx.AsyncClient(timeout=s.request_timeout)
    yield
    await app.state.http.aclose()


settings = get_settings()
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    summary="Drive, configure and watch an Enabot EBO SE 2 over HTTP.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"],
    allow_headers=["*"], allow_credentials=False,
)


def get_engine(request: Request, s: Settings = Depends(get_settings)) -> EngineClient:
    return EngineClient(request.app.state.http, s)


# ---------------------------------------------------------------- meta (no auth)
_STATIC = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/sandbox")


@app.get("/sandbox", include_in_schema=False)
async def sandbox():
    return FileResponse(_STATIC / "sandbox.html")


@app.get("/game", include_in_schema=False)
async def game_index():
    p = Path("/app/game_web/index.html")
    if not p.exists():
        return RedirectResponse("/sandbox")
    return FileResponse(p)


@app.get("/health", tags=["meta"], summary="Liveness probe (no auth)")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- v1 (auth)
v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@v1.get("/status", tags=["meta"], response_model=Status)
async def get_status(eng: EngineClient = Depends(get_engine), s: Settings = Depends(get_settings)):
    reachable = await eng.ping()
    count = len(await eng.robots()) if reachable else 0
    return Status(version=s.api_version, engine_reachable=reachable, robot_count=count)


@v1.get("/account", tags=["meta"])
async def get_account(eng: EngineClient = Depends(get_engine)):
    return await eng.account()


@v1.get("/voices", tags=["tts"], response_model=Voices, summary="Available TTS voices & languages")
async def get_voices():
    return _VOICES


# ---- robots ----
@v1.get("/robots", tags=["robots"], response_model=list[Robot])
async def list_robots(eng: EngineClient = Depends(get_engine)):
    return [Robot.from_engine(rb) for rb in await eng.robots()]


@v1.get("/robots/{robot_id}", tags=["robots"], response_model=Robot)
async def get_robot(robot_id: str, eng: EngineClient = Depends(get_engine)):
    return Robot.from_engine(await eng.robot(robot_id))


@v1.get("/robots/{robot_id}/state", tags=["robots"], response_model=RobotState)
async def get_state(robot_id: str, eng: EngineClient = Depends(get_engine)):
    return RobotState(**((await eng.robot(robot_id)).get("state") or {}))


# ---- settings ----
@v1.get("/robots/{robot_id}/settings", tags=["settings"])
async def get_settings_(robot_id: str, eng: EngineClient = Depends(get_engine)):
    st = (await eng.robot(robot_id)).get("state") or {}
    return {k: st.get(k) for k in _SETTINGS_KEYS if k in st}


@v1.patch("/robots/{robot_id}/settings", tags=["settings"], response_model=CommandResult,
          summary="Set any subset of parameters")
async def patch_settings(robot_id: str, body: SettingsPatch,
                         eng: EngineClient = Depends(get_engine)):
    await eng.robot(robot_id)  # 404 if unknown
    fields = body.model_dump(exclude_none=True)
    if not fields:
        return CommandResult(robot_id=robot_id, ok=True, detail="nothing to change", applied={})
    mapping: dict[str, tuple[str, str]] = {}
    for k, v in fields.items():
        if k in ("night_vision", "video_quality", "image_style", "move_mode"):
            mapping[k] = (f"{k}/set", v)
        elif k in ("avoid_obstacle", "sports_record", "laser", "camera", "listen"):
            mapping[k] = (f"{k}/set", _onoff(v))
        else:  # volume, talkback_volume, speed
            mapping[k] = (f"{k}/set", str(v))
    for _, (suffix, payload) in mapping.items():
        await eng.cmd(robot_id, suffix, payload)
    return CommandResult(robot_id=robot_id, applied=fields)


# ---- movement ----
@v1.post("/robots/{robot_id}/move", tags=["movement"], response_model=CommandResult,
         summary="Drive (direction+speed, or raw vector)")
async def move(robot_id: str, body: MoveRequest, eng: EngineClient = Depends(get_engine)):
    vec = body.to_vector()
    await eng.cmd(robot_id, "move/vector", json.dumps(vec))
    return CommandResult(robot_id=robot_id, applied=vec)


@v1.post("/robots/{robot_id}/stop", tags=["movement"], response_model=CommandResult)
async def stop(robot_id: str, eng: EngineClient = Depends(get_engine)):
    await eng.cmd(robot_id, "move/vector", json.dumps({"ly": 0, "rx": 0, "hold": 0, "buttons": 0}))
    return CommandResult(robot_id=robot_id, detail="stopped")


@v1.post("/robots/{robot_id}/dock", tags=["movement"], response_model=CommandResult,
         summary="Return to charging base")
async def dock(robot_id: str, eng: EngineClient = Depends(get_engine)):
    await eng.cmd(robot_id, "dock", "")
    return CommandResult(robot_id=robot_id, detail="returning to base")


@v1.post("/robots/{robot_id}/wake", tags=["power"], response_model=CommandResult)
async def wake(robot_id: str, eng: EngineClient = Depends(get_engine)):
    await eng.cmd(robot_id, "wake", "")
    return CommandResult(robot_id=robot_id, detail="waking")


@v1.post("/robots/{robot_id}/sleep", tags=["power"], response_model=CommandResult)
async def sleep(robot_id: str, eng: EngineClient = Depends(get_engine)):
    await eng.cmd(robot_id, "sleep/set", "on")
    return CommandResult(robot_id=robot_id, detail="sleeping")


# ---- actions ----
@v1.post("/robots/{robot_id}/say", tags=["tts"], response_model=CommandResult,
         summary="Text-to-speech")
async def say(robot_id: str, body: SayRequest, eng: EngineClient = Depends(get_engine)):
    if body.timbre or body.language:
        payload = json.dumps({k: v for k, v in
                              {"text": body.text, "timbre": body.timbre,
                               "language": body.language}.items() if v})
    else:
        payload = body.text
    await eng.cmd(robot_id, "say", payload)
    return CommandResult(robot_id=robot_id, detail="speaking",
                         applied={"text": body.text, "timbre": body.timbre,
                                  "language": body.language})


@v1.post("/robots/{robot_id}/patrol", tags=["actions"], response_model=CommandResult,
         summary="Schedule Pet Fun Patrol")
async def patrol(robot_id: str, body: PatrolRequest, eng: EngineClient = Depends(get_engine)):
    data = {"id": body.slot_id, "enable": int(body.enable), "startHour": body.start_hour,
            "startMinute": body.start_minute, "repeat": body.repeat,
            "recording": int(body.recording)}
    await eng.cmd(robot_id, "cmd", json.dumps({"id": 104017, "data": data}))
    return CommandResult(robot_id=robot_id, applied=data)


@v1.post("/robots/{robot_id}/commands", tags=["actions"], response_model=CommandResult,
         summary="Raw RTM opcode (advanced)")
async def raw_command(robot_id: str, body: RawCommand, eng: EngineClient = Depends(get_engine)):
    await eng.cmd(robot_id, "cmd", json.dumps({"id": body.id, "data": body.data or {}}))
    return CommandResult(robot_id=robot_id, applied={"id": body.id, "data": body.data or {}})


# ---- media ----
@v1.get("/robots/{robot_id}/snapshot", tags=["media"],
        summary="Latest JPEG still",
        responses={200: {"content": {"image/jpeg": {}}}})
async def snapshot(robot_id: str, eng: EngineClient = Depends(get_engine)):
    return Response(await eng.snapshot(robot_id), media_type="image/jpeg")


@v1.get("/robots/{robot_id}/stream", tags=["media"], response_model=StreamInfo)
async def stream_info(robot_id: str, request: Request, s: Settings = Depends(get_settings),
                      eng: EngineClient = Depends(get_engine)):
    await eng.robot(robot_id)
    base = str(request.base_url).rstrip("/")
    return StreamInfo(
        rtsp_url=f"rtsp://{s.rtsp_public_host}:{s.rtsp_port}/{robot_id}",
        mjpeg_url=f"{base}/api/v1/robots/{robot_id}/stream/mjpeg",
    )


@v1.get("/robots/{robot_id}/stream/mjpeg", tags=["media"], summary="Live MJPEG (browser <img>)")
async def stream_mjpeg(robot_id: str, eng: EngineClient = Depends(get_engine)):
    await eng.robot(robot_id)
    return StreamingResponse(
        eng.mjpeg(robot_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


app.include_router(v1)

# vision / game layer (ebo-vision worker ingest + game entity state + detections stream)
from .game import router as game_router  # noqa: E402
app.include_router(game_router)


# ---------------------------------------------------------------- realtime (WS)
@app.websocket("/api/v1/robots/{robot_id}/events")
async def events(ws: WebSocket, robot_id: str, token: str | None = Query(default=None)):
    s = get_settings()
    keys = s.api_key_set
    supplied = token or (ws.headers.get("authorization", "").removeprefix("Bearer ").strip() or None)
    if keys and supplied not in keys and not s.allow_no_auth:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()
    eng = EngineClient(ws.app.state.http, s)
    try:
        while True:
            try:
                rb = await eng.robot(robot_id)
                await ws.send_json({"id": robot_id, "online": bool(rb.get("online")),
                                    "state": rb.get("state") or {}})
            except Exception as e:  # keep the socket alive across transient engine hiccups
                await ws.send_json({"id": robot_id, "error": str(e)})
            import asyncio
            await asyncio.sleep(s.events_poll_seconds)
    except WebSocketDisconnect:
        return
