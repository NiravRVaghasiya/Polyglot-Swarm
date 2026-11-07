"""HTTP middleware: correlation, access log, metrics, limits, headers (ADR-0035).

All three are plain ASGI middleware (not ``BaseHTTPMiddleware``), so they
never buffer bodies and context variables flow into the endpoint.

- :class:`RequestContextMiddleware` — gives every request an id (a valid
  incoming ``X-Request-ID`` is reused, otherwise a new one), echoes it on the
  response, writes one structured access-log line and records HTTP metrics.
  The log line has method, route template, status, duration and request id —
  never the query string, body, token or user id.
- :class:`BodySizeLimitMiddleware` — rejects bodies over
  ``settings.max_request_bytes`` with 413, from ``Content-Length`` or while
  streaming.
- :class:`SecurityHeadersMiddleware` — conservative headers for a JSON API.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from src.observability import metrics
from src.observability.context import reset_request_id, set_request_id

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

access_log = logging.getLogger("polyglot.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


async def _send_json(send: Send, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = set_request_id(request_id)
        # Also on the scope: the 500 handler runs outside this middleware.
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            route = _route_template(scope)
            method = str(scope.get("method", ""))
            metrics.HTTP_REQUESTS.inc(method=method, route=route, status=str(status))
            metrics.HTTP_LATENCY.observe(elapsed, method=method, route=route)
            access_log.info(
                "%s %s %d %.1fms",
                method,
                route,
                status,
                elapsed * 1000,
                extra={
                    "http_method": method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )
            reset_request_id(token)


class _BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        too_large = {"detail": {"code": "too_large", "message": "request body too large"}}
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await _send_json(send, 413, too_large)
                    return
            except ValueError:
                await _send_json(send, 400, {"detail": "invalid Content-Length"})
                return
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not started:
                await _send_json(send, 413, too_large)


class SecurityHeadersMiddleware:
    _BASE = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"camera=(), geolocation=(), microphone=()"),
        (b"cross-origin-opener-policy", b"same-origin"),
    ]

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        is_docs = path.startswith(("/docs", "/redoc", "/openapi"))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                extra = list(self._BASE)
                if not is_docs:  # the docs UI needs its scripts and styles
                    extra.append(
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
                    )
                if path.startswith("/api/"):
                    extra.append((b"cache-control", b"no-store"))
                if self.hsts:
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                headers += [(k, v) for k, v in extra if k not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
