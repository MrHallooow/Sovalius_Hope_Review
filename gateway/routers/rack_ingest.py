"""Rack->review violation ingestion (separate trust domain).

POST /violations/from-rack   { id, type, ... } -> { id, status, duplicate }

Closes deployment plan §10.1's rack->review seam (gateway_api_contract.md,
"Rack->review violation ingestion"): the on-prem rack's review_push worker
POSTs a citation-class violation it captured and the review gateway ingests
it into the normal review queue as `pending` — reviewers see it exactly like
any other violation.

TRUST: the rack is NOT a reviewer and holds NO reviewer JWT. This endpoint is
guarded by a SEPARATE shared secret (X-Rack-Secret, constant-time compared),
matching the dispatch gateway's /detections posture and this codebase's own
bridge_worker inbound analog. An empty/unprovisioned secret fail-closed-
refuses every request — there is no dev auto-seed (see config.py
rack_ingress_secret).

IDENTITY: the rack mints the canonical violation_uid at capture time
(format V-<CODE>-<YYMMDD>-<SUFFIX>, or a legacy V-LEGACY-<n> placeholder) and
it becomes this gateway's Violation.id VERBATIM — nobody here re-mints or
re-derives it.

IDEMPOTENCY: keyed on `id` (the violation_uid). A re-push (retry, at-least-
once delivery) returns the FIRST receipt with duplicate:true and does NOT
update the stored row — first-write-wins in v1; field updates are out of
scope and a re-push is not an update channel. The DB primary key is the race
backstop: a concurrent double-insert raises IntegrityError, which we catch,
roll back, and re-fetch the winner.

AUDIT: no audit_log row is written here. audit.py's own contract (see its
module docstring + the _PREFIX action-code table) scopes the chain to
reviewer/user/camera/service/login ACTS — a human decision or admin change.
Machine ingestion is not a reviewer act (mirrors detections.py's /detections
and /tips on the dispatch gateway, which are also unaudited machine seams);
the violation's own `history` list gets an "ingested_from_rack" entry instead
(mirrors seed.py's ai-flagged "flagged" history entry shape), which is
sufficient provenance since the row starts at `pending` and every subsequent
REVIEW action already writes its own audit row via routers.violations.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..schemas import RackViolationIngest
from ..util import iso

router = APIRouter(tags=["Rack Ingest"])


def require_rack_secret(x_rack_secret: str | None = Header(default=None)) -> None:
    """Constant-time check of the review-side rack shared secret. Fail-closed
    when the gateway has no secret provisioned (empty) so this endpoint is
    never an open violation-injection hole — same posture as the dispatch
    gateway's /detections and this gateway's own bridge_worker secret."""
    expected = settings.rack_ingress_secret or ""
    presented = x_rack_secret or ""
    if not expected or not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid rack credential")


def _parse_captured_at(raw: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail="capturedAtUtc must be a valid ISO-8601 timestamp"
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.post("/violations/from-rack")
def ingest_from_rack(
    body: RackViolationIngest,
    _rack: None = Depends(require_rack_secret),
    db: Session = Depends(get_db),
) -> dict:
    vid = (body.id or "").strip()
    if not vid or len(vid) > 64:
        raise HTTPException(
            status_code=400, detail="id is required and must be <= 64 characters"
        )
    vtype = (body.type or "").strip()
    if not vtype:
        raise HTTPException(status_code=400, detail="type is required")
    if not body.capturedAtUtc:
        raise HTTPException(status_code=400, detail="capturedAtUtc is required")
    captured_at = _parse_captured_at(body.capturedAtUtc)

    # ---- idempotent fast path: already ingested -> first-write-wins ----
    existing = db.get(models.Violation, vid)
    if existing is not None:
        return {
            "id": vid,
            "status": existing.status or "pending",
            "duplicate": True,
        }

    loc = body.location
    evidence = body.evidence
    now = datetime.now(timezone.utc)

    violation = models.Violation(
        id=vid,
        type=vtype,
        speed=body.speedMph,
        speed_limit=body.speedLimitMph,
        plate=body.plate or "",
        vehicle="",
        location=(loc.label if loc else "") or "",
        gps_lat=loc.lat if loc else None,
        gps_lng=loc.lng if loc else None,
        cameras=body.cameras or [],
        camera=body.camera or "",
        date=captured_at,
        confidence=body.confidence,
        weather=body.weather or "",
        ai_summary="",
        status="pending",
        notes="",
        pinned=False,
        history=[
            {
                "action": "ingested_from_rack",
                "by": "system",
                "at": iso(now),
                "notes": "Ingested from rack review_push worker",
            }
        ],
        clip_url=(evidence.clipUrl if evidence else "") or "",
        raw_clip_url=(evidence.rawClipUrl if evidence else "") or "",
        screenshot_url=(evidence.screenshotUrl if evidence else "") or "",
        # citable is REQUIRED in the contract's payload, but we store exactly
        # what was sent (including an honest None if omitted) rather than
        # rejecting the row: downstream dispatch already fail-closes on any
        # non-True citable at the citation bridge (gateway_api_contract.md,
        # "Camera citations"), so storing the true rack verdict matters more
        # than gatekeeping it here.
        citable=body.citable,
        gate_reason=body.gateReason or "",
    )
    db.add(violation)
    try:
        db.commit()
    except IntegrityError:
        # Race backstop: two concurrent pushes for the same id both passed the
        # existing-row check above. The DB's primary key is the real
        # arbiter — roll back our insert and report the winner's row as the
        # duplicate receipt (first-write-wins, same as the fast path above).
        db.rollback()
        winner = db.get(models.Violation, vid)
        if winner is None:  # pragma: no cover - only if the winner also failed
            raise
        return {"id": vid, "status": winner.status or "pending", "duplicate": True}

    return {"id": vid, "status": "pending", "duplicate": False}
