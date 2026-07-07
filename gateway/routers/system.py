"""Services board + system status snapshot.

GET   /services        any authenticated user (the renderer's status screen)
PATCH /services/{id}   admin ROLE only; allowlisted fields; audited
GET   /system/status   any authenticated user; tolerates an EMPTY table
                       (fresh un-seeded DB) by returning row=null

/health and /ready (unauthenticated probes) live in app.py — this router is
the authenticated, DB-backed view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import audit, models
from ..bridge_worker import outbox_snapshot
from ..db import get_db
from ..schemas import ServicePatch
from ..security import current_user, require_roles
from ..util import iso

router = APIRouter(tags=["System"])

_admin_gate = require_roles("admin")

# The ONLY mutable service columns (server-side allowlist — the legacy IPC
# interpolated arbitrary client-supplied column names into UPDATE SQL).
_SERVICE_FIELDS = ("status", "detail", "uptime", "latency", "usage")


def _service_json(s: models.Service) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "status": s.status,
        "detail": s.detail or "",
        "uptime": s.uptime or "",
        "latency": s.latency or "",
        "usage": s.usage or "",
        "updatedAt": iso(s.updated_at),
    }


@router.get("/services")
def list_services(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.query(models.Service).order_by(models.Service.id.asc()).all()
    return {"ok": True, "services": [_service_json(s) for s in rows]}


@router.patch("/services/{service_id}")
def update_service(
    service_id: int,
    req: ServicePatch,
    actor: models.User = Depends(_admin_gate),
    db: Session = Depends(get_db),
) -> dict:
    svc = db.get(models.Service, service_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")

    changes: dict = {}
    for field in _SERVICE_FIELDS:
        value = getattr(req, field)
        if value is not None:
            changes[field] = value
    if not changes:
        raise HTTPException(status_code=400, detail="No valid fields")

    for k, v in changes.items():
        setattr(svc, k, v)
    svc.updated_at = models._utcnow()  # server clock, mirroring updated_at=NOW()
    audit.record(
        db,
        officer=actor.username,
        action="service_change",
        notes=f"updated service '{svc.name}' ({', '.join(sorted(changes))})",
        detail={
            "op": "update",
            "serviceId": svc.id,
            "service": svc.name,
            "fields": sorted(changes),
        },
    )
    db.commit()
    return {"ok": True, "service": _service_json(svc)}


@router.get("/system/status")
def system_status(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Latest-row-wins snapshot (ORDER BY timestamp DESC LIMIT 1, id as the
    tie-break). An EMPTY table is a valid state (fresh DB, ingest not running
    yet) -> {ok:true, row:null}, matching the legacy handler's row: null."""
    row = (
        db.query(models.SystemStatus)
        .order_by(
            models.SystemStatus.timestamp.desc(), models.SystemStatus.id.desc()
        )
        .first()
    )
    # Stuck-outbox metric (citation-lifecycle bridge, gateway_api_contract.md
    # "Camera citations"): surfaced regardless of whether the push worker is
    # currently running, so a disabled/misconfigured worker still shows a
    # growing backlog instead of silently hiding it.
    outbox = outbox_snapshot(db)

    if row is None:
        return {"ok": True, "row": None, "outbox": outbox}
    return {
        "ok": True,
        "row": {
            "id": row.id,
            "timestamp": iso(row.timestamp),
            "status": row.status,
            "detail": row.detail or {},
        },
        "outbox": outbox,
    }
