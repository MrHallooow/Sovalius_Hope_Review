"""Notifications — mirrors the main.js notification IPC trio.

GET   /notifications               -> {ok, rows} newest first, LIMIT 50
                                      (db:get-notifications)
PATCH /notifications/{id}          -> {ok} mark one read
                                      (db:mark-notification-read; body is
                                      optional — {"read": bool} defaults true)
POST  /notifications/mark-all-read -> {ok, updated}
                                      (db:mark-all-notifications-read)

Read state is PER USER (models.NotificationRead). The notifications table
carries a single global ``read`` column, so one reviewer opening a
notification used to mark it read for everyone on every desk; the API now
reports and writes the caller's own read state and leaves the legacy column
alone.

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


def _row(n: models.Notification, read: bool) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "msg": n.msg,
        "at": iso(n.at),
        "read": bool(read),
    }


def _read_ids(db: Session, user_id: int, notification_ids: list[int]) -> set[int]:
    """Which of these notifications THIS user has read."""
    if not notification_ids:
        return set()
    rows = (
        db.query(models.NotificationRead.notification_id)
        .filter(
            models.NotificationRead.user_id == user_id,
            models.NotificationRead.notification_id.in_(notification_ids),
        )
        .all()
    )
    return {r[0] for r in rows}


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
    read = _read_ids(db, user.id, [n.id for n in rows])
    return {"ok": True, "rows": [_row(n, n.id in read) for n in rows]}


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
    # explicitly mark unread. Only THIS user's read state moves.
    want_read = True if req is None or req.read is None else bool(req.read)
    existing = db.get(models.NotificationRead, (n.id, user.id))
    if want_read and existing is None:
        db.add(models.NotificationRead(notification_id=n.id, user_id=user.id))
    elif not want_read and existing is not None:
        db.delete(existing)
    db.commit()
    return {"ok": True, "row": _row(n, want_read)}


@router.post("/notifications/mark-all-read")
def mark_all_read(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    ids = [r[0] for r in db.query(models.Notification.id).all()]
    already = _read_ids(db, user.id, ids)
    updated = 0
    for nid in ids:
        if nid not in already:
            db.add(models.NotificationRead(notification_id=nid, user_id=user.id))
            updated += 1
    db.commit()
    return {"ok": True, "updated": updated}
