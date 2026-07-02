"""GET /analytics — reproduces electron/main.js db:get-analytics semantics.

Shape: {ok, data:{today, week, month, byType, hourly}} where each bucket is
{total, approved, dismissed, pending} counted over violations LEFT JOIN
violation_reviews with COALESCE(r.status,'pending'); byType is an INTEGER
percentage distribution over ALL violations (no date filter, JS Math.round
semantics: half rounds UP); hourly is a 24-slot histogram of TODAY's
violations by hour.

main.js computed the window starts as LOCAL midnight (new Date().setHours(0))
minus 0/7/30 days, then compared in UTC — mirrored here with the server's
local timezone. Everything is built from SQLAlchemy constructs (func.count /
case / extract) so the SAME code runs on dev SQLite and prod Postgres; the
legacy raw SQL used PG-only FILTER clauses and referenced v.timestamp /
v.violation_type, which don't exist in schema.sql (date/type do — the task
contract pins date/type).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, extract, func
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..security import current_user

router = APIRouter(tags=["Analytics"])


def _js_round(x: float) -> int:
    """JS Math.round: half always rounds UP (Python's round() is banker's)."""
    return int(math.floor(x + 0.5))


def _local_midnight_utc(now: datetime | None = None) -> datetime:
    """Today's LOCAL midnight expressed in UTC — what main.js's
    ``new Date(); d.setHours(0,0,0,0); d.toISOString()`` produced."""
    now_local = (now or datetime.now(timezone.utc)).astimezone()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


def _bucket(db: Session, since: datetime) -> dict:
    """{total, approved, dismissed, pending} for violations dated >= since,
    status COALESCEd from the LEFT-JOINed review row ('pending' if none)."""
    review_status = func.coalesce(models.ViolationReview.status, "pending")
    row = (
        db.query(
            func.count(models.Violation.id).label("total"),
            func.sum(case((review_status == "approved", 1), else_=0)).label(
                "approved"
            ),
            func.sum(case((review_status == "dismissed", 1), else_=0)).label(
                "dismissed"
            ),
            func.sum(case((review_status == "pending", 1), else_=0)).label("pending"),
        )
        .select_from(models.Violation)
        .outerjoin(
            models.ViolationReview,
            models.ViolationReview.violation_id == models.Violation.id,
        )
        .filter(models.Violation.date >= since)
        .one()
    )
    # SUM over zero rows is NULL — coalesce in Python for both backends.
    return {
        "total": int(row.total or 0),
        "approved": int(row.approved or 0),
        "dismissed": int(row.dismissed or 0),
        "pending": int(row.pending or 0),
    }


@router.get("/analytics")
def analytics(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    today_start = _local_midnight_utc()
    week_start = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    # ---- type distribution: integer % over ALL violations (no date filter) ----
    count_expr = func.count(models.Violation.id)
    type_rows = (
        db.query(models.Violation.type, count_expr)
        .group_by(models.Violation.type)
        .order_by(count_expr.desc())
        .all()
    )
    total_all = sum(int(c) for _, c in type_rows) or 1  # `|| 1` guards div-by-0
    by_type = {t: _js_round(int(c) * 100.0 / total_all) for t, c in type_rows}

    # ---- hourly histogram of TODAY's violations ----
    # extract('hour') compiles to EXTRACT(HOUR ...) on Postgres and
    # CAST(STRFTIME('%H', ...) AS INTEGER) on SQLite — hour of the stored
    # (UTC) timestamp on both.
    hour_expr = extract("hour", models.Violation.date).label("hr")
    hourly = [0] * 24
    for hr, c in (
        db.query(hour_expr, func.count(models.Violation.id))
        .filter(models.Violation.date >= today_start)
        .group_by(hour_expr)
        .all()
    ):
        idx = int(hr)
        if 0 <= idx <= 23:
            hourly[idx] = int(c)

    return {
        "ok": True,
        "data": {
            "today": _bucket(db, today_start),
            "week": _bucket(db, week_start),
            "month": _bucket(db, month_start),
            "byType": by_type,
            "hourly": hourly,
        },
    }
