"""Bearer-key authentication. Clients send `Authorization: Bearer <key>`; keys come from env."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False, description="API key issued to your client")


def require_api_key(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    keys = settings.api_key_set
    if not keys:
        # No keys configured. Only allowed if the operator opted into an open API.
        if settings.allow_no_auth:
            return "anonymous"
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API has no API_KEYS configured and ALLOW_NO_AUTH is false.",
        )
    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials not in keys:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing or invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return creds.credentials
