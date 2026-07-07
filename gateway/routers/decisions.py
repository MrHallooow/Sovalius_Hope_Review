"""GET /decisions/feed — the read-only review-decision feed (see
gateway_api_contract.md "Review-gateway decision feed", in the "Camera
citations" section).

This is (a) the reconciliation authority for the citation-lifecycle bridge —
any "approved" event here without a matching dispatch citation is a delivery
bug — and (b) the future flywheel inlet (deployment plan sec 10.4):
dismissals/reopens accumulate from day one even though nothing consumes them
yet.

Cursors on ``models.DecisionOutbox.id`` — the SAME monotonic, gap-free event
id the push worker uses as its dispatch-side idempotency key
(``sourceEventId``). ALL decisions appear (approved/dismissed/reopened) — no
filtering by decision kind, and no exposure of delivery-state columns
(``delivered_at``/``attempts``/``parked_at``/...) — those are push-worker
internals, not part of what was decided.

Everything returned is read straight off ``row.payload`` — the verbatim event
snapshot recorded AT DECISION TIME (see models.DecisionOutbox docstring) — so
the feed reflects history even if the live violation/review rows later
change or are gone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..security import require_privilege

router = APIRouter(tags=["Decisions"])

# Reconciliation/flywheel consumers only — same live-row privilege gate style
# as audit.py's canViewAudit-gated /audit/log.
_feed_gate = require_privilege("canExport")

_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000


@router.get("/decisions/feed")
def feed(
    since: int = 0,
    limit: int = _DEFAULT_LIMIT,
    user: models.User = Depends(_feed_gate),
    db: Session = Depends(get_db),
) -> dict:
    if since < 0:
        raise HTTPException(status_code=400, detail="since must be >= 0")
    if limit < 1 or limit > _MAX_LIMIT:
        raise HTTPException(
            status_code=400, detail=f"limit must be between 1 and {_MAX_LIMIT}"
        )

    rows = (
        db.query(models.DecisionOutbox)
        .filter(models.DecisionOutbox.id > since)
        .order_by(models.DecisionOutbox.id.asc())
        .limit(limit)
        .all()
    )

    items = []
    for row in rows:
        payload = row.payload or {}
        items.append(
            {
                "eventId": row.id,
                "violationId": row.violation_id,
                "decision": row.decision,
                "reviewedBy": payload.get("reviewedBy"),
                "reviewedAtUtc": payload.get("reviewedAtUtc"),
                "notes": payload.get("reviewNotes"),
                "violation": payload.get("violation"),
            }
        )

    out: dict = {"items": items}
    if len(items) == limit:
        # Possibly more beyond this page — only advertise a cursor when the
        # page was actually full (an under-full page means we drained
        # everything past `since`).
        out["nextEventId"] = items[-1]["eventId"]
    return out
