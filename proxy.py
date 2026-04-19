from __future__ import annotations

import base64
import hashlib
import html
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send


UPSTREAM = os.environ.get("OPENBB_UPSTREAM", "http://127.0.0.1:8002")
BEARER_TOKEN = os.environ.get("OPENBB_BEARER_TOKEN") or ""
SERVICE_NAME = "openbb-mcp"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8001"))

_PUBLIC_PREFIXES = ("/healthz", "/.well-known/", "/oauth/")

_clients: dict[str, dict] = {}
_codes: dict[str, dict] = {}
_CODE_TTL = 600

_client = httpx.AsyncClient(
    base_url=UPSTREAM,
    timeout=httpx.Timeout(connect=10.0, read=None, write=60.0, pool=None),
)


def _now() -> int:
    return int(time.time())


def _base_url(request: Request) -> str:
    headers = {k.lower(): v for k, v in request.headers.items()}
    scheme = headers.get("x-forwarded-proto") or request.url.scheme
    host = headers.get("x-forwarded-host") or headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": SERVICE_NAME})


async def protected_resource_metadata(request: Request) -> JSONResponse:
    base = _base_url(request)
    return JSONResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp"],
    })


async def authorization_server_metadata(request: Request) -> JSONResponse:
    base = _base_url(request)
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp"],
    })


async def register(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    client_id = secrets.token_urlsafe(24)
    redirect_uris = body.get("redirect_uris") or []
    _clients[client_id] = {
        "redirect_uris": redirect_uris,
        "client_name": body.get("client_name", "unknown"),
    }
    return JSONResponse({
        "client_id": client_id,
        "client_id_issued_at": _now(),
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "client_name": body.get("client_name", "unknown"),
    }, status_code=201)


async def authorize(request: Request):
    if request.method == "GET":
        p = request.query_params
        client_id = p.get("client_id", "")
        redirect_uri = p.get("redirect_uri", "")
        state = p.get("state", "")
        code_challenge = p.get("code_challenge", "")
        code_challenge_method = p.get("code_challenge_method", "")
        scope = p.get("scope", "mcp")

        if client_id not in _clients:
            return JSONResponse({"error": "invalid_client"}, status_code=400)

        client_name = html.escape(_clients[client_id].get("client_name", "unknown"))
        form_html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Authorize openbb-mcp</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 420px; margin: 60px auto; padding: 0 20px; color: #222; }}
h2 {{ margin-top: 0; }}
.client {{ background: #f4f4f4; padding: 12px; border-radius: 6px; font-size: 14px; margin: 16px 0; }}
input[type=password] {{ width: 100%; padding: 10px; font-size: 15px; box-sizing: border-box; margin: 8px 0 16px; }}
button {{ background: #1a73e8; color: white; border: 0; padding: 10px 16px; font-size: 15px; border-radius: 6px; cursor: pointer; width: 100%; }}
</style></head><body>
<h2>Authorize openbb-mcp</h2>
<p>Grant access to OpenBB Platform financial data tools.</p>
<div class="client"><b>{client_name}</b><br>wants to connect as <code>{html.escape(client_id)[:16]}…</code></div>
<form method="post" action="/oauth/authorize">
  <input type="hidden" name="client_id" value="{html.escape(client_id)}">
  <input type="hidden" name="redirect_uri" value="{html.escape(redirect_uri)}">
  <input type="hidden" name="state" value="{html.escape(state)}">
  <input type="hidden" name="code_challenge" value="{html.escape(code_challenge)}">
  <input type="hidden" name="code_challenge_method" value="{html.escape(code_challenge_method)}">
  <input type="hidden" name="scope" value="{html.escape(scope)}">
  <label>Master token:<br>
    <input type="password" name="token" autofocus required>
  </label>
  <button type="submit">Authorize</button>
</form>
</body></html>"""
        return HTMLResponse(form_html)

    form = await request.form()
    submitted = (form.get("token") or "").strip()
    if not BEARER_TOKEN or submitted != BEARER_TOKEN:
        return HTMLResponse(
            "<p style='font-family:sans-serif;max-width:420px;margin:60px auto'>"
            "Invalid master token. <a href='javascript:history.back()'>Go back</a></p>",
            status_code=401,
        )

    client_id = form.get("client_id") or ""
    redirect_uri = form.get("redirect_uri") or ""
    state = form.get("state") or ""
    if client_id not in _clients:
        return JSONResponse({"error": "invalid_client"}, status_code=400)

    code = secrets.token_urlsafe(24)
    _codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": form.get("code_challenge") or "",
        "code_challenge_method": form.get("code_challenge_method") or "",
        "expires_at": _now() + _CODE_TTL,
    }
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


async def token(request: Request) -> JSONResponse:
    form = await request.form()
    if form.get("grant_type") != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    code = form.get("code") or ""
    entry = _codes.pop(code, None)
    if not entry or _now() > entry["expires_at"]:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    if entry.get("code_challenge"):
        verifier = form.get("code_verifier") or ""
        if entry["code_challenge_method"] == "S256":
            h = hashlib.sha256(verifier.encode()).digest()
            computed = base64.urlsafe_b64encode(h).decode().rstrip("=")
            if computed != entry["code_challenge"]:
                return JSONResponse({"error": "invalid_grant", "error_description": "PKCE failed"}, status_code=400)
        elif entry["code_challenge_method"] == "plain":
            if verifier != entry["code_challenge"]:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
        else:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

    return JSONResponse({
        "access_token": BEARER_TOKEN,
        "token_type": "Bearer",
        "expires_in": 60 * 60 * 24 * 365,
        "scope": "mcp",
    })


_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
    "content-length", "content-encoding",
}


async def proxy_upstream(request: Request) -> StreamingResponse:
    path = request.url.path
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "authorization", *_HOP_BY_HOP)
    }
    body = await request.body()

    upstream_req = _client.build_request(
        request.method,
        path,
        params=request.query_params,
        headers=fwd_headers,
        content=body,
    )
    upstream_resp = await _client.send(upstream_req, stream=True)

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    return StreamingResponse(
        upstream_resp.aiter_raw(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        background=BackgroundTask(upstream_resp.aclose),
    )


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._token:
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES):
            await self._app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer ") or auth.split(" ", 1)[1].strip() != self._token:
            await _send_401(send, headers.get("host", ""), headers.get("x-forwarded-proto", "https"))
            return

        await self._app(scope, receive, send)


async def _send_401(send: Send, host: str, scheme: str) -> None:
    resource_meta = f"{scheme}://{host}/.well-known/oauth-protected-resource" if host else ""
    www_auth = (
        f'Bearer realm="{SERVICE_NAME}", resource_metadata="{resource_meta}"'
        if resource_meta else f'Bearer realm="{SERVICE_NAME}"'
    )
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", www_auth.encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": b'{"error":"unauthorized"}',
    })


def build_app() -> ASGIApp:
    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", authorization_server_metadata, methods=["GET"]),
        Route("/oauth/register", register, methods=["POST"]),
        Route("/oauth/authorize", authorize, methods=["GET", "POST"]),
        Route("/oauth/token", token, methods=["POST"]),
        Route("/{path:path}", proxy_upstream, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    ]
    app = Starlette(routes=routes)
    return BearerAuthMiddleware(app, token=BEARER_TOKEN)


if __name__ == "__main__":
    if not BEARER_TOKEN:
        raise SystemExit("OPENBB_BEARER_TOKEN is required")
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="info")
