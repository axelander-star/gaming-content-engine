"""Webhooks from outside, authenticated by signature instead of login.

Reached through its own tunnel host (Caddy ``:8083``, no Cloudflare Access), which
forwards only ``POST /github`` here. Exempt from the Access check; every request
must carry a valid GitHub HMAC signature (``services/deploy_hook.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.deps import AppSettings
from services import deploy_hook

router = APIRouter(prefix="/hooks", tags=["hooks"], include_in_schema=False)


@router.post("/github")
async def github_push(request: Request, settings: AppSettings) -> JSONResponse:
    """GitHub ``push``/``ping``: a push to main starts the server update at once."""
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > deploy_hook.MAX_BODY_BYTES:
            break
    try:
        result = deploy_hook.handle(
            settings,
            body,
            event=request.headers.get("x-github-event"),
            signature=request.headers.get("x-hub-signature-256"),
            delivery=request.headers.get("x-github-delivery"),
        )
    except deploy_hook.HookError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)
    return JSONResponse(
        {"action": result.action, "detail": result.detail}, status_code=result.status
    )
