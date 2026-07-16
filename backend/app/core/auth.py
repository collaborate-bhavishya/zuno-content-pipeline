"""Requires a valid Supabase Auth session on every gated request.

The frontend signs users in via Supabase Auth and sends the resulting access
token as `Authorization: Bearer <token>`. We validate it by asking Supabase's
own Auth server whether the token is live (rather than verifying a JWT secret
locally) — this needs no extra secret beyond SUPABASE_URL/SUPABASE_KEY, and it
naturally honors token expiry and revocation.
"""
import logging
from typing import Optional

from fastapi import Header, HTTPException

from app.core.db import get_client

log = logging.getLogger(__name__)


async def require_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        result = get_client().auth.get_user(token)
    except Exception as e:
        log.warning("Auth check failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if not result or not result.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return result.user
