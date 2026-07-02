"""Violations: board read + the review decision surface.

GET   /violations                  -> {ok, rows} — violations LEFT JOIN
                                      violation_reviews, newest first; row
                                      shape mirrors electron/main.js
                                      db:get-violations (v.* + review_status /
                                      reviewed_by / reviewed_at / review_notes /
                                      review_pinned / review_history).
PATCH /violations/{id}/review      -> per-transition privilege checks; the
                                      server sets reviewed_by (from the token
                                      user) + reviewed_at (server clock) and
                                      APPENDS to history — client-supplied
                                      reviewed_by/reviewed_at/history are
                                      ignored. Every change writes a
                                      tamper-evident audit row.
GET   /violations/{id}/history     -> {ok, violationId, history} — full
                                      provenance: the violation's own history
                                      (e.g. the AI "flagged" entry) followed by
                                      the review history.

Contract note: main.js SELECTs ``v.*`` then aliases the review columns; with
node-pg's duplicate-column semantics the LEFT JOIN's r.reviewed_by /
r.reviewed_at overwrote the violation's own columns in the returned row, so
``reviewed_by`` / ``reviewed_at`` here come from the REVIEW row (null when the
violation is unreviewed) — matching what the renderer actually received.
main.js also ordered by ``v.timestamp`` / selected ``v.violation_type``, which
do not exist in schema.sql (date/type do) — the task contract pins date/type.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import audit, models
from ..db import get_db
from ..schemas import ReviewPatch
from ..security import current_user, require_privilege
from ..util import iso

router = APIRouter(tags=["Violations"])

_STATUSES = {"pending", "approved", "dismissed"}

# Route-level gate: touching a review at all needs at least one review
# privilege (live-row read; revocation is immediate). The per-TRANSITION
# checks inside the handler are stricter.
_review_gate = require_privilege("canApprove", "canDismiss", "canRevise")


def _violation_row(v: models.Violation, r: models.ViolationReview | None) -> dict:
    return {
        # ---- v.* (violations columns, schema-parity names) ----
        "id": v.id,
        "type": v.type,
        "speed": v.speed,
        "speed_limit": v.speed_limit,
        "plate": v.plate or "",
        "vehicle": v.vehicle or "",
        "location": v.location or "",
        "gps_lat": v.gps_lat,
        "gps_lng": v.gps_lng,
        "cameras": v.cameras or [],
        "camera": v.camera or "",
        "date": iso(v.date),
        "confidence": v.confidence,
        "weather": v.weather or "",
        "ai_summary": v.ai_summary or "",
        "status": v.status or "pending",  # legacy inline field (kept by v.*)
        "notes": v.notes or "",
        "pinned": bool(v.pinned),
        "history": v.history or [],
        "clip_url": v.clip_url or "",
        "raw_clip_url": v.raw_clip_url or "",
        "screenshot_url": v.screenshot_url or "",
        # ---- LEFT JOIN review aliases (authoritative review record) ----
        "review_status": (r.status if r is not None else None) or "pending",
        # node-pg duplicate-name semantics: these two surfaced from r, not v.
        "reviewed_by": r.reviewed_by if r is not None else None,
        "reviewed_at": iso(r.reviewed_at) if r is not None else None,
        "review_notes": (r.notes if r is not None else None) or "",
        "review_pinned": bool(r.pinned) if r is not None else False,
        "review_history": (r.history if r is not None else None) or [],
    }


def _review_row(r: models.ViolationReview) -> dict:
    """Mirror of main.js db:update-violation's RETURNING * row."""
    return {
        "violation_id": r.violation_id,
        "status": r.status or "pending",
        "reviewed_by": r.reviewed_by,
        "reviewed_at": iso(r.reviewed_at),
        "notes": r.notes or "",
        "pinned": bool(r.pinned),
        "history": r.history or [],
    }


@router.get("/violations")
def list_violations(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    pairs = (
        db.query(models.Violation, models.ViolationReview)
        .outerjoin(
            models.ViolationReview,
            models.ViolationReview.violation_id == models.Violation.id,
        )
        .order_by(models.Violation.date.desc())
        .all()
    )
    return {"ok": True, "rows": [_violation_row(v, r) for v, r in pairs]}


@router.get("/violations/{violation_id}/history")
def violation_history(
    violation_id: str,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    v = db.get(models.Violation, violation_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Unknown violation")
    r = db.get(models.ViolationReview, violation_id)
    # Full provenance: the ingest-time violation history (AI "flagged" entry)
    # followed by every review decision appended server-side.
    history = [*(v.history or []), *((r.history if r is not None else None) or [])]
    return {"ok": True, "violationId": violation_id, "history": history}


@router.patch("/violations/{violation_id}/review")
def patch_review(
    violation_id: str,
    req: ReviewPatch,
    user: models.User = Depends(_review_gate),
    db: Session = Depends(get_db),
) -> dict:
    v = db.get(models.Violation, violation_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Unknown violation")

    review = db.get(models.ViolationReview, violation_id)
    current = (review.status if review is not None else None) or "pending"
    cur_notes = (review.notes if review is not None else None) or ""
    cur_pinned = bool(review.pinned) if review is not None else False

    # ---- validate + normalise the requested status ----
    new_status: str | None = None
    if req.status is not None:
        new_status = str(req.status).strip().lower()
        if new_status not in _STATUSES:
            raise HTTPException(
                status_code=400,
                detail="Invalid status (expected pending|approved|dismissed)",
            )

    status_changed = new_status is not None and new_status != current
    notes_changed = req.notes is not None and req.notes != cur_notes
    pinned_changed = req.pinned is not None and bool(req.pinned) != cur_pinned

    # ---- per-transition privilege checks (live privilege dict; no implicit
    # role bypass). Approve needs canApprove, dismiss needs canDismiss, and
    # CHANGING an already-decided status additionally needs canRevise (a
    # decided->pending reopen is canRevise alone). ----
    privs = user.privileges or {}
    if status_changed:
        if current != "pending" and privs.get("canRevise") is not True:
            raise HTTPException(
                status_code=403,
                detail="canRevise privilege required to change a decided review",
            )
        if new_status == "approved" and privs.get("canApprove") is not True:
            raise HTTPException(
                status_code=403, detail="canApprove privilege required"
            )
        if new_status == "dismissed" and privs.get("canDismiss") is not True:
            raise HTTPException(
                status_code=403, detail="canDismiss privilege required"
            )

    # ---- no-op: nothing to write, nothing to audit ----
    if not (status_changed or notes_changed or pinned_changed):
        row = (
            _review_row(review)
            if review is not None
            else {
                "violation_id": violation_id,
                "status": "pending",
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": "",
                "pinned": False,
                "history": [],
            }
        )
        return {"ok": True, "row": row, "changed": False}

    now = models._utcnow()
    # reviewed_by mirrors the legacy renderer's officerName (display name);
    # ALWAYS derived from the authenticated token user, never the body.
    actor = user.display_name or user.username

    if review is None:
        review = models.ViolationReview(
            violation_id=violation_id,
            status="pending",
            reviewed_by=None,
            reviewed_at=None,
            notes="",
            pinned=False,
            history=[],
        )
        db.add(review)

    # ---- history APPEND (never client-replaced; ReviewPatch has no history
    # field and extra body keys are ignored) ----
    entries: list[dict] = []
    if status_changed:
        entries.append(
            {
                "action": new_status,
                "by": actor,
                "at": iso(now),
                "notes": req.notes if req.notes is not None else cur_notes,
                "from": current,
            }
        )
    elif notes_changed:
        entries.append(
            {"action": "note_updated", "by": actor, "at": iso(now), "notes": req.notes}
        )
    if pinned_changed:
        entries.append(
            {
                "action": "pinned" if bool(req.pinned) else "unpinned",
                "by": actor,
                "at": iso(now),
            }
        )
    # JSON columns don't track in-place mutation — reassign, never .append().
    review.history = [*(review.history or []), *entries]

    # ---- apply (server-side reviewed_by / reviewed_at on status change) ----
    if status_changed:
        review.status = new_status
        review.reviewed_by = actor
        review.reviewed_at = now
    if req.notes is not None:
        review.notes = req.notes
    if req.pinned is not None:
        review.pinned = bool(req.pinned)

    # ---- tamper-evident audit row, committed atomically with the review ----
    if status_changed:
        action = {
            "approved": "review_approved",
            "dismissed": "review_dismissed",
        }.get(new_status, "review_reopened")
    elif pinned_changed:
        action = "pinned"
    else:
        action = "review_notes"
    audit.record(
        db,
        officer=user.username,
        action=action,
        violation_id=violation_id,
        notes=(req.notes or "")[:512],
        detail={
            "from": current,
            "to": review.status or "pending",
            "pinned": bool(review.pinned),
            "notesChanged": notes_changed,
        },
    )
    db.commit()
    return {"ok": True, "row": _review_row(review), "changed": True}
