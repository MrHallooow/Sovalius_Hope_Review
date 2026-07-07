"""FastAPI app factory for the H.O.P.E. Review Gateway (port 8090).

CORS is deliberately NOT configured: the caller is the Electron MAIN process
(Node's http stack), which does not enforce the browser same-origin policy, so
CORS headers would be dead weight — and a permissive policy would only widen
the surface if the port were ever exposed. If the renderer ever calls the
gateway directly, add a locked-down allowlist (the app:// origin), never "*".
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import audit as audit_module
from . import bridge_worker
from .config import settings
from .db import SessionLocal, init_db
from .logging_setup import (
    configure_logging,
    get_request_id,
    reset_request_context,
    set_request_context,
    update_request_context,
)
from .ratelimit import LoginThrottle
from .routers import (
    analytics,
    audit,
    auth,
    cameras,
    decisions,
    evidence,
    notifications,
    prefs,
    rack_ingest,
    system,
    users,
    violations,
)
from .seed import seed
from .storage import build_store
from .util import short_id

logger = logging.getLogger("revgw")


def _error_body(status: int, message: str) -> dict:
    # Shape the Electron app's error mapping understands: TOP-LEVEL
    # code/message/retryable (not nested) — same contract as the dispatch
    # gateway's Flutter client.
    code = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        429: "rate_limited",
    }.get(status, "error")
    # 429 is retryable so the client backs off and retries after the forwarded
    # Retry-After window instead of surfacing a hard failure.
    retryable = status >= 500 or status in (401, 429)
    return {"code": code, "message": message, "retryable": retryable}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Citation-lifecycle bridge push worker: only started when BOTH
    # bridge_url and bridge_secret are configured (fail-closed — see
    # bridge_worker.is_enabled / config.py). Cancelled cleanly on shutdown.
    task: asyncio.Task | None = None
    if bridge_worker.is_enabled(settings):
        task = asyncio.create_task(bridge_worker.run_forever(settings))
    else:
        logger.info("bridge_worker: disabled (GWREV_BRIDGE_URL/SECRET unset)")
    app.state.bridge_worker_task = task
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    # Structured JSON logging first so every line below (including init) is
    # shaped and correlatable. Reads GWREV_LOG_LEVEL / GWREV_LOG_JSON inside.
    configure_logging()

    app = FastAPI(
        title="SVG H.O.P.E — Review Gateway", version="0.1.0", lifespan=_lifespan
    )

    # One process-wide login throttle held on app.state (mutable runtime state,
    # test-injectable / resettable) — NOT a module global.
    app.state.login_throttle = LoginThrottle(
        max_failures=settings.login_max_failures,
        window_sec=settings.login_window_sec,
        lockout_sec=settings.login_lockout_sec,
        user_lockout_sec=settings.login_user_lockout_sec,
    )

    # Register the append-only audit guard before any session flushes.
    audit_module.install_guards()

    # Build the evidence object store ONCE (local disk by default; lazy-boto3
    # S3 when GWREV_EVIDENCE_STORE=s3). Held on app.state so the (future)
    # evidence router reads it per-request and tests can override per app.
    app.state.evidence_store = build_store(settings)

    init_db()
    if settings.seed_on_start:
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()

    for module in (
        auth,
        audit,
        violations,
        analytics,
        notifications,
        cameras,
        evidence,
        users,
        prefs,
        system,
        decisions,
        rack_ingest,
    ):
        app.include_router(module.router)

    # ------------------------------------------------------------------ #
    # Request context + body-size cap + access log middleware. Runs OUTSIDE
    # routing so the 413 short-circuit fires before validation, and so every
    # response — including error responses — carries X-Request-Id.
    # ------------------------------------------------------------------ #
    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or short_id("req")
        token = set_request_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        # Body-size cap from Content-Length. Chunked/no-length POSTs aren't
        # capped here — a known residual gap; the JSON bodies this gateway
        # accepts are tiny anyway (evidence bytes never flow through JSON).
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > settings.max_body_bytes:
                    update_request_context(status=413, latency_ms=0.0)
                    logger.warning("request body too large: %s bytes", cl)
                    resp = JSONResponse(
                        status_code=413,
                        content={
                            "code": "payload_too_large",
                            "message": "Request body too large",
                            "retryable": False,
                        },
                    )
                    resp.headers["X-Request-Id"] = request_id
                    return resp
            except ValueError:
                pass  # malformed Content-Length — let the stack handle it

        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            # Echo the correlation id on every response (incl. error responses
            # produced by the exception handlers, which run within call_next).
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000.0, 3)
            update_request_context(status=status, latency_ms=latency_ms)
            # One structured access-log line per request.
            logger.info("access")
            reset_request_context(token)

    @app.get("/health", tags=["System"])
    def health() -> dict:
        # LIVENESS only — process is up. No DB/IO so a transient dependency
        # blip never restart-loops the host. Readiness lives at /ready.
        return {"status": "ok", "service": "review-gateway", "version": "0.1.0"}

    @app.get("/ready", tags=["System"])
    def ready() -> JSONResponse:
        # READINESS — probe the real dependencies: DB reachable + evidence
        # storage writable. 200 when both pass; 503 (retryable) on any failure,
        # body shaped TOP-LEVEL {code,message,retryable} + a per-check map.
        checks = {"db": "ok", "storage": "ok"}

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))  # SQLAlchemy 2.0 requires text()
        except Exception:  # pragma: no cover - exercised only on a real DB fault
            logger.exception("readiness DB check failed")
            checks["db"] = "error"
        finally:
            db.close()

        # Storage check: a write+unlink temp file is a truthful "is it
        # writable" probe (more reliable than os.access on Windows).
        try:
            ev_dir = settings.evidence_dir
            ev_dir.mkdir(parents=True, exist_ok=True)
            probe = ev_dir / f".ready-{short_id('probe')}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception:  # pragma: no cover - exercised only on a real FS fault
            logger.exception("readiness storage check failed")
            checks["storage"] = "error"

        if all(v == "ok" for v in checks.values()):
            return JSONResponse(
                status_code=200, content={"status": "ready", "checks": checks}
            )
        return JSONResponse(
            status_code=503,
            content={
                "code": "unavailable",
                "message": "dependency check failed",
                "retryable": True,
                "checks": checks,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException):
        # Forward any headers set on the exception (e.g. Retry-After on a 429);
        # the default handler drops them, which would lose the client backoff.
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.status_code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={"code": "invalid", "message": "Invalid request", "retryable": False},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # The request_id is read from the contextvar so this 500 line
        # correlates with the access line emitted by the middleware.
        logger.exception(
            "Unhandled gateway error (request_id=%s): %s", get_request_id(), exc
        )
        return JSONResponse(status_code=500, content=_error_body(500, "Internal error"))

    return app
