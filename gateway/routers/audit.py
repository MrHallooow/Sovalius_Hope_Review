"""Audit endpoints.

GET /audit/verify -> chain-integrity metadata (supervisor/admin ROLE gate)
GET /audit/head   -> {seq, hash, count}     (supervisor/admin ROLE gate)
GET /audit/log    -> recent audited actions (canViewAudit PRIVILEGE gate —
                     reads the LIVE user row, so revocation is immediate)

/verify and /head return ONLY integrity METADATA — never bulk row contents.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import audit, models
from ..db import get_db
from ..security import require_privilege, require_roles
from ..util import iso

router = APIRouter(tags=["Audit"])

# Only supervisors / admins may inspect chain integrity.
_verify_gate = require_roles("supervisor", "admin")
# Browsing the audit log itself is privilege-gated per the review contract.
_log_gate = require_privilege("canViewAudit")


@router.get("/audit/verify")
def verify(
    user: models.User = Depends(_verify_gate),
    db: Session = Depends(get_db),
) -> dict:
    r = audit.verify_chain(db)
    return {
        "ok": r["ok"],
        "checked": r["checked"],
        "headSeq": r["head_seq"],
        "headHash": r["head_hash"],
        "firstBrokenSeq": r["first_broken_seq"],
        "reason": r["reason"],
    }


@router.get("/audit/head")
def chain_head(
    user: models.User = Depends(_verify_gate),
    db: Session = Depends(get_db),
) -> dict:
    h = audit.head(db)
    return {"seq": h["seq"], "hash": h["hash"], "count": h["count"]}


@router.get("/audit/log")
def list_rows(
    limit: int = 200,
    user: models.User = Depends(_log_gate),
    db: Session = Depends(get_db),
) -> dict:
    """Recent audited actions, newest first (WHO did WHAT and WHEN). Rows are
    written SERVER-SIDE on every review/user/camera mutation and login —
    client-supplied officer/at values are never trusted anywhere."""
    n = max(1, min(1000, int(limit) if isinstance(limit, int) else 200))
    rows = (
        db.query(models.AuditLog)
        .order_by(models.AuditLog.seq.desc())
        .limit(n)
        .all()
    )
    items = [
        {
            "seq": r.seq,
            "auditRef": r.id,
            "officer": r.officer,
            "action": r.action,
            "violationId": r.violation_id or "",
            "notes": r.notes or "",
            "at": iso(r.at),
        }
        for r in rows
    ]
    return {"items": items}
