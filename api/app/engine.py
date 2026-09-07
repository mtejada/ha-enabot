"""Async client for the internal EBO engine data API (the process that holds the Agora session).

The engine speaks a small HTTP API on :8098, guarded by the `X-Enabot-Token` header:
  GET  /api/robots                     -> [ {node,online,state,name,sn,mac,model,rtsp}, ... ]
  GET  /api/account                    -> {email}
  GET  /api/snapshot?node=<node>       -> image/jpeg (or 404 if none yet)
  GET  /api/mjpeg?node=<node>          -> multipart/x-mixed-replace stream
  POST /api/cmd {node,suffix,payload}  -> {ok:true} | 400 {error}

This module turns those into typed calls and raises HTTPException with clean messages on failure.
Robots are addressed by their engine `node` name — that is the `{robot_id}` in the public API.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

import httpx
from fastapi import HTTPException, status

from .config import Settings


class EngineClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self._c = client
        self._s = settings

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Enabot-Token": self._s.engine_token}

    async def _get(self, path: str, **kw) -> httpx.Response:
        try:
            return await self._c.get(self._s.engine_url + path, headers=self._headers, **kw)
        except httpx.HTTPError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"engine unreachable: {e}") from e

    # --- reads ---
    async def robots(self) -> list[dict[str, Any]]:
        r = await self._get("/api/robots")
        if r.status_code != 200:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "engine /api/robots failed")
        return r.json()

    async def robot(self, node: str) -> dict[str, Any]:
        for rb in await self.robots():
            if rb.get("node") == node:
                return rb
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"robot '{node}' not found")

    async def account(self) -> dict[str, Any]:
        r = await self._get("/api/account")
        return r.json() if r.status_code == 200 else {}

    async def snapshot(self, node: str) -> bytes:
        r = await self._get("/api/snapshot", params={"node": node})
        if r.status_code != 200 or not r.content:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "no frame available (robot asleep/docked, or stream warming up)",
            )
        return r.content

    async def mjpeg(self, node: str) -> AsyncIterator[bytes]:
        url = self._s.engine_url + "/api/mjpeg"
        async with self._c.stream(
            "GET", url, headers=self._headers, params={"node": node}, timeout=None
        ) as resp:
            if resp.status_code != 200:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "mjpeg unavailable")
            async for chunk in resp.aiter_bytes():
                yield chunk

    # --- writes ---
    async def cmd(self, node: str, suffix: str, payload: str = "") -> dict[str, Any]:
        try:
            r = await self._c.post(
                self._s.engine_url + "/api/cmd",
                headers=self._headers,
                json={"node": node, "suffix": suffix, "payload": payload},
            )
        except httpx.HTTPError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"engine unreachable: {e}") from e
        if r.status_code == 400:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                (r.json() or {}).get("error", "bad command"))
        if r.status_code != 200:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"engine cmd failed ({r.status_code})")
        return r.json()

    async def ping(self) -> bool:
        try:
            r = await self._get("/api/robots")
            return r.status_code == 200
        except HTTPException:
            return False
