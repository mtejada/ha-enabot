"""Bearer-key auth. Clients send `Authorization: Bearer <key>`; keys come from env.

Browsers can't set headers on `<img>`/`<video>`/EventSource, so a `?token=` (or `?api_key=`)
query param is also accepted — handy for the MJPEG/snapshot endpoints and the sandbox UI.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False, description="API key issued to your client")


def require_api_key(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    keys = settings.api_key_set
    if not keys:
        if settings.allow_no_auth:
            return "anonymous"
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API has no API_KEYS configured and ALLOW_NO_AUTH is false.",
        )
    supplied: str | None = None
    if creds is not None and creds.scheme.lower() == "bearer":
        supplied = creds.credentials
    else:
        supplied = request.query_params.get("token") or request.query_params.get("api_key")
    if supplied not in keys:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return supplied
