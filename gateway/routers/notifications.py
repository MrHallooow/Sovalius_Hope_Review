"""Notifications — mirrors the main.js notification IPC trio.

GET   /notifications               -> {ok, rows} newest first, LIMIT 50
                                      (db:get-notifications)
PATCH /notifications/{id}          -> {ok} mark one read
                                      (db:mark-notification-read; body is
                                      optional — {"read": bool} defaults true)
POST  /notifications/mark-all-read -> {ok, updated}
                                      (db:mark-all-notifications-read)

Read-state changes are per-desk UI state, not review/user/camera mutations,
so they are deliberately NOT audited (the audit chain records evidentiary
actions, not inbox housekeeping).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..schemas import NotificationPatch
from ..security import current_user
from ..util import iso

router = APIRouter(tags=["Notifications"])


def _row(n: models.Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "msg": n.msg,
        "at": iso(n.at),
        "read": bool(n.read),
    }


@router.get("/notifications")
def list_notifications(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.query(models.Notification)
        # id DESC tie-break keeps equal-timestamp rows deterministic.
        .order_by(models.Notification.at.desc(), models.Notification.id.desc())
        .limit(50)
        .all()
    )
    return {"ok": True, "rows": [_row(n) for n in rows]}


@router.patch("/notifications/{notification_id}")
def mark_read(
    notification_id: int,
    req: NotificationPatch | None = None,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    n = db.get(models.Notification, notification_id)
    if n is None:
        raise HTTPException(status_code=404, detail="Unknown notification")
    # No body (the legacy IPC shape) means "mark read"; {"read": false} can
    # explicitly mark unread.
    n.read = True if req is None or req.read is None else bool(req.read)
    db.commit()
    return {"ok": True, "row": _row(n)}


@router.post("/notifications/mark-all-read")
def mark_all_read(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    updated = (
        db.query(models.Notification)
        .filter(models.Notification.read == False)  # noqa: E712
        .update({"read": True}, synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "updated": int(updated)}
