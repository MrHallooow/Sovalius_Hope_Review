"""Citation-lifecycle bridge — step 2: the push worker that delivers
APPROVED ``decision_outbox`` rows to the dispatch gateway's
``POST /citations/from-review`` (see gateway_api_contract.md, "Camera
citations — the review->service bridge", and models.DecisionOutbox's
docstring for the append-only / same-txn / event-id contract this worker
must respect).

Disabled by default: the worker only starts when BOTH ``GWREV_BRIDGE_URL``
and ``GWREV_BRIDGE_SECRET`` are set (see config.py). An unprovisioned secret
is the same fail-closed posture as the dispatch gateway's own X-Rack-Secret /
X-Bridge-Secret checks — nothing is ever POSTed anywhere by default.

Outcome handling per row (contract section "Camera citations", "Rules"):
  * 2xx (incl. ``duplicate: true``)      -> delivered_at=now, attempts+=1, last_error cleared.
  * 422 non_citable / unmapped_offence   -> PERMANENTLY parked (parked_at=now); attempts+=1,
                                             last_error set; never auto-retried.
  * anything else (network error, 401,
    5xx, timeout, non-2xx/422)          -> attempts+=1, last_error set, left undelivered;
                                             next_attempt_at pushed out by per-row exponential
                                             backoff + jitter.

No row is ever deleted, and ``payload`` is never touched by this module — see
models.DecisionOutbox for the columns this worker is allowed to write.

Split for testability (BUILD item 3): ``select_due`` is a pure function over
plain rows + ``now`` (no DB, no I/O) so the backoff/parking logic is unit
tested without a database or event loop; ``drain_once`` performs exactly one
"select a batch, deliver each, persist outcomes" pass synchronously so tests
can call it directly instead of driving the poll loop.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from . import config, models
from .config import Settings
from .db import SessionLocal

logger = logging.getLogger("revgw")

# ---------------------------------------------------------------------------
# Backoff: base 5s, doubling per attempt, capped at 15min, +/-20% jitter.
# ---------------------------------------------------------------------------
_BACKOFF_BASE_SEC = 5.0
_BACKOFF_CAP_SEC = 15 * 60.0
_BACKOFF_JITTER_FRAC = 0.20

# Non-retryable error codes per gateway_api_contract.md ("Camera citations",
# "Rules") — these PARK the row rather than scheduling a retry.
# court_only_offence: the dispatch gateway's legally-correct refusal for a
# type whose offence is court-only (e.g. dangerous/reckless driving) — it can
# never be a fixed-penalty citation; the row waits, parked, for the future
# camera->summons path.
_NON_RETRYABLE_CODES = {"non_citable", "unmapped_offence", "court_only_offence"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_backoff_sec(attempts: int) -> float:
    """Exponential backoff with a cap and up to +20% jitter. ``attempts`` is
    the attempt count AFTER the failure being backed off from (i.e. the
    caller increments attempts, then computes the delay for the next try)."""
    base = min(_BACKOFF_CAP_SEC, _BACKOFF_BASE_SEC * (2**attempts))
    jitter = base * random.random() * _BACKOFF_JITTER_FRAC
    return base + jitter


@dataclass
class DeliveryOutcome:
    """Pure description of what happened attempting to deliver one row —
    kept separate from the ORM row so the deciding logic (park vs retry vs
    deliver) is unit-testable without a DB session."""

    delivered: bool = False
    parked: bool = False
    error: str = ""


def _aware(dt: datetime) -> datetime:
    """SQLite round-trips DateTime(timezone=True) values as naive (pysqlite
    drops the offset on read) — normalise to UTC-aware before any comparison
    so this works identically on SQLite (dev/test) and Postgres (prod)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def select_due(
    rows: list[models.DecisionOutbox], now: datetime
) -> list[models.DecisionOutbox]:
    """Pure filter: which undelivered, unparked, approved rows are eligible
    for a delivery attempt RIGHT NOW, oldest-first. No DB access — callers
    pass in already-queried rows (or hand-built test doubles) so backoff/due
    logic is testable without a database.

    A row qualifies when: decision == "approved", delivered_at is NULL,
    parked_at is NULL, and (next_attempt_at is NULL or next_attempt_at <=
    now). ``dismissed``/``reopened`` rows never qualify — they are
    feed-only and delivered_at is never set for them (see
    models.DecisionOutbox)."""
    now = _aware(now)
    due = [
        r
        for r in rows
        if r.decision == "approved"
        and r.delivered_at is None
        and r.parked_at is None
        and (r.next_attempt_at is None or _aware(r.next_attempt_at) <= now)
    ]
    due.sort(key=lambda r: (_aware(r.created_at), r.id))
    return due


def _outcome_for_response(resp: httpx.Response) -> DeliveryOutcome:
    if 200 <= resp.status_code < 300:
        return DeliveryOutcome(delivered=True)

    if resp.status_code == 422:
        code = ""
        try:
            code = str(resp.json().get("code", ""))
        except Exception:
            pass
        if code in _NON_RETRYABLE_CODES:
            return DeliveryOutcome(
                parked=True, error=f"422 {code or resp.text[:200]}"
            )
        # An unrecognised 422 shape is treated conservatively as retryable —
        # only the two documented non-retryable codes ever park a row.
        return DeliveryOutcome(error=f"422 {code or resp.text[:200]}")

    return DeliveryOutcome(error=f"{resp.status_code} {resp.text[:200]}")


def _apply_outcome(
    row: models.DecisionOutbox, outcome: DeliveryOutcome, now: datetime
) -> None:
    """Mutate ONLY the worker-owned columns on ``row``. Never touches
    ``payload``/``violation_id``/``decision``/``created_at``."""
    row.attempts += 1
    if outcome.delivered:
        row.delivered_at = now
        row.last_error = ""
        row.next_attempt_at = None
        return

    row.last_error = outcome.error
    if outcome.parked:
        row.parked_at = now
        row.next_attempt_at = None
        logger.warning(
            "bridge_worker: parked outbox row %s (violation=%s): %s",
            row.id,
            row.violation_id,
            outcome.error,
        )
        return

    delay = compute_backoff_sec(row.attempts)
    row.next_attempt_at = now + timedelta(seconds=delay)
    logger.warning(
        "bridge_worker: delivery failed for outbox row %s (attempt %d, "
        "retry in %.1fs): %s",
        row.id,
        row.attempts,
        delay,
        outcome.error,
    )


def _deliver(
    client: httpx.Client | httpx.AsyncClient,
    cfg: Settings,
    row: models.DecisionOutbox,
) -> DeliveryOutcome:
    body = {"sourceEventId": row.id, **row.payload}
    try:
        resp = client.post(
            f"{cfg.bridge_url}/citations/from-review",
            json=body,
            headers={"X-Bridge-Secret": cfg.bridge_secret},
        )
    except httpx.TimeoutException as exc:
        return DeliveryOutcome(error=f"timeout: {exc}")
    except httpx.HTTPError as exc:
        return DeliveryOutcome(error=f"connection error: {exc}")
    return _outcome_for_response(resp)


async def _adeliver(
    client: httpx.AsyncClient, cfg: Settings, row: models.DecisionOutbox
) -> DeliveryOutcome:
    body = {"sourceEventId": row.id, **row.payload}
    try:
        resp = await client.post(
            f"{cfg.bridge_url}/citations/from-review",
            json=body,
            headers={"X-Bridge-Secret": cfg.bridge_secret},
        )
    except httpx.TimeoutException as exc:
        return DeliveryOutcome(error=f"timeout: {exc}")
    except httpx.HTTPError as exc:
        return DeliveryOutcome(error=f"connection error: {exc}")
    return _outcome_for_response(resp)


_TIMEOUT = httpx.Timeout(connect=3.0, timeout=10.0)


def drain_once(
    db: Session,
    cfg: Settings | None = None,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> int:
    """Select one batch of due rows and attempt delivery for each,
    synchronously. Returns the number of rows processed (delivered, parked,
    or failed-and-rescheduled — never a count of successes only).

    Refuses (returns 0, does nothing) when the worker is disabled
    (bridge_url or bridge_secret unset) — mirrors the "never start the task"
    guard in the lifespan hook so a misconfigured drain_once call in a test
    or a stray manual invocation can't accidentally fire real HTTP calls."""
    cfg = cfg or config.settings
    if not cfg.bridge_url or not cfg.bridge_secret:
        return 0

    now = now or _utcnow()

    candidates = (
        db.query(models.DecisionOutbox)
        .filter(
            models.DecisionOutbox.decision == "approved",
            models.DecisionOutbox.delivered_at.is_(None),
            models.DecisionOutbox.parked_at.is_(None),
        )
        .order_by(models.DecisionOutbox.created_at.asc(), models.DecisionOutbox.id.asc())
        .limit(cfg.bridge_batch * 4)  # headroom before the pure due-filter
        .all()
    )
    due = select_due(candidates, now)[: cfg.bridge_batch]
    if not due:
        return 0

    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT)
    try:
        for row in due:
            outcome = _deliver(client, cfg, row)
            _apply_outcome(row, outcome, now)
            if outcome.delivered:
                logger.info(
                    "bridge_worker: delivered outbox row %s (violation=%s)",
                    row.id,
                    row.violation_id,
                )
            db.commit()
    finally:
        if owns_client:
            client.close()

    return len(due)


async def adrain_once(
    db: Session,
    cfg: Settings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> int:
    """Async twin of :func:`drain_once` for the lifespan-owned poll loop
    (avoids blocking the event loop on every HTTP call)."""
    cfg = cfg or config.settings
    if not cfg.bridge_url or not cfg.bridge_secret:
        return 0

    now = now or _utcnow()

    candidates = (
        db.query(models.DecisionOutbox)
        .filter(
            models.DecisionOutbox.decision == "approved",
            models.DecisionOutbox.delivered_at.is_(None),
            models.DecisionOutbox.parked_at.is_(None),
        )
        .order_by(models.DecisionOutbox.created_at.asc(), models.DecisionOutbox.id.asc())
        .limit(cfg.bridge_batch * 4)
        .all()
    )
    due = select_due(candidates, now)[: cfg.bridge_batch]
    if not due:
        return 0

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        for row in due:
            outcome = await _adeliver(client, cfg, row)
            _apply_outcome(row, outcome, now)
            if outcome.delivered:
                logger.info(
                    "bridge_worker: delivered outbox row %s (violation=%s)",
                    row.id,
                    row.violation_id,
                )
            db.commit()
    finally:
        if owns_client:
            await client.aclose()

    return len(due)


async def run_forever(cfg: Settings | None = None) -> None:
    """The lifespan-owned poll loop. Cancelled cleanly on shutdown (the
    CancelledError propagates out of the ``asyncio.sleep`` and this coroutine
    exits — no swallowed-cancellation anti-pattern)."""
    cfg = cfg or config.settings
    logger.info(
        "bridge_worker: starting (url=%s, poll=%.1fs, batch=%d)",
        cfg.bridge_url,
        cfg.bridge_poll_sec,
        cfg.bridge_batch,
    )
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            while True:
                try:
                    db = SessionLocal()
                    try:
                        await adrain_once(db, cfg, client=client)
                    finally:
                        db.close()
                except Exception:
                    # A transient failure (DB hiccup, unexpected bug in one
                    # pass) must NOT kill this task for the rest of the
                    # process lifetime — a dead worker looks identical to a
                    # healthy-but-idle one from the outside, and the only
                    # symptom would be the outbox backlog slowly aging. Log
                    # and try again next poll. (CancelledError is a
                    # BaseException and is deliberately not caught here.)
                    logger.exception("bridge_worker: drain pass failed")
                await asyncio.sleep(cfg.bridge_poll_sec)
        except asyncio.CancelledError:
            logger.info("bridge_worker: stopping")
            raise


def is_enabled(cfg: Settings | None = None) -> bool:
    cfg = cfg or config.settings
    return bool(cfg.bridge_url and cfg.bridge_secret)


def outbox_snapshot(db: Session, now: datetime | None = None) -> dict:
    """Stuck-outbox metrics for GET /system/status's ``outbox`` block.
    Undelivered counts ONLY approved+unparked rows — dismissed/reopened rows
    are feed-only and must never contribute (per models.DecisionOutbox)."""
    now = now or _utcnow()

    undelivered_q = db.query(models.DecisionOutbox).filter(
        models.DecisionOutbox.decision == "approved",
        models.DecisionOutbox.delivered_at.is_(None),
        models.DecisionOutbox.parked_at.is_(None),
    )
    undelivered = undelivered_q.count()

    quarantined = (
        db.query(models.DecisionOutbox)
        .filter(models.DecisionOutbox.parked_at.isnot(None))
        .count()
    )

    oldest = (
        undelivered_q.order_by(models.DecisionOutbox.created_at.asc()).first()
    )
    oldest_age = None
    if oldest is not None:
        created = oldest.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        oldest_age = max(0.0, (now - created).total_seconds())

    last_error_row = (
        db.query(models.DecisionOutbox)
        .filter(models.DecisionOutbox.last_error != "")
        .order_by(models.DecisionOutbox.id.desc())
        .first()
    )
    last_error = last_error_row.last_error if last_error_row is not None else ""

    return {
        "undelivered": undelivered,
        "quarantined": quarantined,
        "oldest_undelivered_age_sec": oldest_age,
        "last_error": last_error,
    }
