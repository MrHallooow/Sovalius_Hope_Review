"""Structured JSON logging + a per-request id contextvar.

Zero new deps: a stdlib ``logging.Formatter`` subclass renders each record as a
single JSON line (json.dumps in ``format()``). The request id / method / path /
status / latency / user id are pulled from a ``contextvars.ContextVar`` set by
the request middleware in app.py, so any log line emitted while handling a
request automatically carries the correlation id.

Honours two env knobs (read inside ``configure_logging`` so tests that set env
before import still take effect):
  - GWREV_LOG_LEVEL (default INFO)
  - GWREV_LOG_JSON  (default '1'; '0' -> human-readable text for local dev)
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from datetime import datetime, timezone

# Per-request correlation context. The middleware sets a fresh dict at the start
# of every request; log records copy the live values in at format() time.
_request_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "revgw_request_ctx", default={}
)

# Keys that the access-log line and the JSON formatter surface from the context.
_CTX_KEYS = ("request_id", "method", "path", "status", "latency_ms", "user_id")


def set_request_context(**fields) -> contextvars.Token:
    """Replace the request context with ``fields`` and return the reset token.

    Returns a token the caller passes to :func:`reset_request_context` in a
    ``finally`` so the contextvar never leaks across requests/threads."""
    return _request_ctx.set(dict(fields))


def update_request_context(**fields) -> None:
    """Merge ``fields`` into the live request context (e.g. stamp user_id /
    status / latency once they are known)."""
    cur = dict(_request_ctx.get())
    cur.update(fields)
    _request_ctx.set(cur)


def reset_request_context(token: contextvars.Token) -> None:
    _request_ctx.reset(token)


def get_request_id() -> str | None:
    return _request_ctx.get().get("request_id")


class JsonFormatter(logging.Formatter):
    """Render a log record as one compact JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = _request_ctx.get()
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _CTX_KEYS:
            val = ctx.get(key)
            if val is not None:
                payload[key] = val
        # Allow callers to attach structured extras via logger.x(..., extra={...}).
        for key, val in getattr(record, "__dict__", {}).items():
            if key.startswith("ctx_") and val is not None:
                payload[key[4:]] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging() -> logging.Logger:
    """Install a single handler on the 'revgw' logger using the JSON (or plain)
    formatter. Idempotent — safe to call once per ``create_app()``."""
    level_name = os.environ.get("GWREV_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    json_mode = os.environ.get("GWREV_LOG_JSON", "1") != "0"

    logger = logging.getLogger("revgw")
    logger.setLevel(level)
    # Drop any handlers we installed on a previous create_app() so repeated app
    # builds (the test suite makes several) don't multiply access-log lines.
    for h in list(logger.handlers):
        if getattr(h, "_revgw_handler", False):
            logger.removeHandler(h)

    handler = logging.StreamHandler()
    handler._revgw_handler = True  # type: ignore[attr-defined]
    if json_mode:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    handler.setLevel(level)
    logger.addHandler(handler)
    # Don't double-emit through the root logger's default handler.
    logger.propagate = False
    return logger
