"""Idempotent DEV seed (GWREV_SEED=1 only; refuses to run when GWREV_ENV=prod).

Seeds three users — admin / supervisor / officer — each with a DISTINCT
random one-time password printed to the console ONCE at creation (the old
admin123-style hardcoded credentials are deliberately retired; production
users are created individually through the app's user-management screen).

For tests, GWREV_SEED_PASSWORD overrides the random generation with a single
known password for all three accounts (mirrors the dispatch gateway's
GATEWAY_SEED_PASSWORD convention).

Also seeds a handful of violations (+ authoritative violation_reviews rows),
cameras, camera lanes, notifications, services and a system_status snapshot —
mirroring the legacy setup-db.js data so the app renders familiar content.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import models
from .config import settings
from .security import hash_password

logger = logging.getLogger("revgw.seed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _one_time_password() -> str:
    # Random-looking, URL-safe, ~16 chars. Printed once; never stored plain.
    return secrets.token_urlsafe(12)


# Privilege sets mirror the legacy setup-users.js matrix.
_USERS = [
    {
        "username": "admin",
        "display_name": "Administrator",
        "role": "admin",
        "privileges": {
            "canApprove": True,
            "canDismiss": True,
            "canRevise": True,
            "canManageUsers": True,
            "canManageCameras": True,
            "canViewAudit": True,
            "canExport": True,
        },
    },
    {
        "username": "supervisor",
        "display_name": "Sgt. Williams",
        "role": "supervisor",
        "privileges": {
            "canApprove": True,
            "canDismiss": True,
            "canRevise": True,
            "canManageUsers": False,
            "canManageCameras": True,
            "canViewAudit": True,
            "canExport": True,
        },
    },
    {
        "username": "officer",
        "display_name": "Cpl. James",
        "role": "officer",
        "privileges": {
            "canApprove": True,
            "canDismiss": True,
            "canRevise": False,
            "canManageUsers": False,
            "canManageCameras": False,
            "canViewAudit": False,
            "canExport": False,
        },
    },
]


def seed(db: Session) -> None:
    # Hard guard: seeding well-known usernames into a production database is
    # how systems get owned.
    if settings.env == "prod":
        logger.warning("seed() refused: GWREV_ENV=prod (dev-only operation)")
        return
    _seed_users(db)
    _seed_cameras(db)
    _seed_violations(db)
    _seed_camera_lanes(db)
    _seed_notifications(db)
    _seed_services(db)
    _seed_system_status(db)
    db.commit()


def _seed_users(db: Session) -> None:
    override = os.environ.get("GWREV_SEED_PASSWORD", "")
    issued: list[tuple[str, str]] = []
    for spec in _USERS:
        existing = (
            db.query(models.User)
            .filter(models.User.username == spec["username"])
            .one_or_none()
        )
        if existing is not None:
            continue
        password = override or _one_time_password()
        db.add(
            models.User(
                username=spec["username"],
                password_hash=hash_password(password),
                display_name=spec["display_name"],
                role=spec["role"],
                privileges=spec["privileges"],
                active=True,
            )
        )
        issued.append((spec["username"], password))
    if issued and not override:
        # Printed ONCE, only for newly-created accounts, dev only.
        print("\n[seed] One-time dev passwords (shown ONCE — change on first login):")
        for username, password in issued:
            print(f"[seed]   {username}: {password}")
        print()


_CAMERAS = [
    ("CAM-AV-07", "Leeward Hwy, Arnos Vale", "online", 30),
    ("CAM-KT-12", "Bay Street, Kingstown", "online", 15),
    ("CAM-KT-03", "Halifax St, Kingstown", "online", 45),
    ("CAM-CQ-02", "Windward Hwy, Calliaqua", "offline", 3600),
    ("CAM-QS-01", "Leeward Hwy, Questelles", "online", 20),
    ("CAM-KT-08", "Vigie Highway, Kingstown", "online", 60),
    ("CAM-KT-15", "Kingstown Bypass", "degraded", 120),
]


def _seed_cameras(db: Session) -> None:
    for cam_id, location, status, ping_ago_sec in _CAMERAS:
        if db.get(models.Camera, cam_id) is None:
            db.add(
                models.Camera(
                    id=cam_id,
                    location=location,
                    status=status,
                    last_ping=_now() - timedelta(seconds=ping_ago_sec),
                )
            )


# (id, type, speed, limit, plate, vehicle, location, lat, lng, cams, cam,
#  date, confidence, weather, summary)
_VIOLATIONS = [
    ("VIO-2026-00147", "Speeding", 78, 50, "SV-4829", "Silver Toyota Corolla",
     "Leeward Highway, Arnos Vale", 13.1339, -61.2108, ["CAM-AV-07", "CAM-AV-08"],
     "CAM-AV-07", "2026-03-20T09:34:12Z", 94.7, "Clear",
     "Vehicle at 78 km/h in 50 zone. Plate SV-4829 at 98.2%."),
    ("VIO-2026-00146", "Reckless Driving", None, None, "SV-7103", "Red Nissan March",
     "Bay Street, Kingstown", 13.1553, -61.2275, ["CAM-KT-12"],
     "CAM-KT-12", "2026-03-20T09:21:45Z", 87.3, "Overcast",
     "Dangerous overtaking across double yellow lines."),
    ("VIO-2026-00145", "Illegal Parking", None, None, "SV-2256", "White Hyundai Tucson",
     "Halifax St, Kingstown", 13.1567, -61.2258, ["CAM-KT-03", "CAM-KT-04"],
     "CAM-KT-03", "2026-03-20T08:55:30Z", 96.1, "Clear",
     "No-parking zone 12+ min. Plate at 99.1%."),
    ("VIO-2026-00144", "Speeding", 65, 40, "SV-9481", "Blue Honda Fit",
     "Windward Highway, Calliaqua", 13.1412, -61.1953, ["CAM-CQ-02"],
     "CAM-CQ-02", "2026-03-20T08:42:18Z", 91.2, "Rain",
     "65 km/h in 40 school zone. Wet road."),
    ("VIO-2026-00143", "Speeding", 72, 50, "SV-4829", "Silver Toyota Corolla",
     "Leeward Highway, Questelles", 13.1721, -61.2489, ["CAM-QS-01"],
     "CAM-QS-01", "2026-03-20T08:15:03Z", 89.8, "Clear",
     "72 km/h in 50 zone. Same plate as VIO-147."),
    ("VIO-2026-00142", "Reckless Driving", None, None, "SV-6640", "Grey Suzuki Swift",
     "Vigie Highway, Kingstown", 13.1601, -61.2312, ["CAM-KT-08"],
     "CAM-KT-08", "2026-03-20T07:58:22Z", 73.4, "Dawn",
     "Sharp U-turn. Low light."),
    ("VIO-2026-00141", "Speeding", 68, 50, "SV-1192", "White Toyota Hiace",
     "Kingstown Bypass", 13.158, -61.23, ["CAM-KT-15"],
     "CAM-KT-15", "2026-03-20T07:30:00Z", 92.5, "Clear",
     "68 km/h in 50 zone."),
]

# Pre-reviewed rows so the board isn't all-pending: (violation_id, status,
# reviewer display name, notes).
_REVIEWS = [
    ("VIO-2026-00143", "approved", "Sgt. Williams", "Clear violation."),
    ("VIO-2026-00142", "dismissed", "Cpl. James", "Low confidence."),
    ("VIO-2026-00141", "approved", "Sgt. Williams", "Clear speeding."),
]


def _seed_violations(db: Session) -> None:
    for (vid, vtype, speed, limit, plate, vehicle, location, lat, lng, cams,
         cam, date, conf, weather, summary) in _VIOLATIONS:
        if db.get(models.Violation, vid) is None:
            db.add(
                models.Violation(
                    id=vid,
                    type=vtype,
                    speed=speed,
                    speed_limit=limit,
                    plate=plate,
                    vehicle=vehicle,
                    location=location,
                    gps_lat=lat,
                    gps_lng=lng,
                    cameras=cams,
                    camera=cam,
                    date=_dt(date),
                    confidence=conf,
                    weather=weather,
                    ai_summary=summary,
                    status="pending",
                    # Rack enforcement-gate verdict. Real data isn't wired yet
                    # (the rack sync is future work) — dev seed data sets this
                    # True so the citation-lifecycle bridge's happy path
                    # (outbox -> future push worker) is testable end-to-end.
                    citable=True,
                    gate_reason="gate: citation class, certified basis",
                    history=[
                        {
                            "action": "flagged",
                            "by": "AI System",
                            "at": date,
                            "notes": "Auto-detected by detection pipeline",
                        }
                    ],
                )
            )
    for vid, status, reviewer, notes in _REVIEWS:
        if db.get(models.ViolationReview, vid) is None:
            reviewed_at = _now() - timedelta(hours=1)
            db.add(
                models.ViolationReview(
                    violation_id=vid,
                    status=status,
                    reviewed_by=reviewer,
                    reviewed_at=reviewed_at,
                    notes=notes,
                    pinned=False,
                    history=[
                        {
                            "action": status,
                            "by": reviewer,
                            "at": reviewed_at.isoformat(),
                            "notes": notes,
                        }
                    ],
                )
            )


def _seed_camera_lanes(db: Session) -> None:
    if db.get(models.CameraLane, "CAM-AV-07") is None:
        db.add(
            models.CameraLane(
                camera_name="CAM-AV-07",
                lane_data={
                    "lanes": [
                        {"id": 1, "label": "NB-1", "points": [[120, 700], [420, 180]]},
                        {"id": 2, "label": "NB-2", "points": [[430, 700], [560, 180]]},
                    ]
                },
                calibration_width=1920,
                calibration_height=1080,
            )
        )


def _seed_notifications(db: Session) -> None:
    if db.query(models.Notification).count() > 0:
        return
    db.add_all(
        [
            models.Notification(
                type="violation",
                msg="New violation VIO-2026-00147 flagged",
                at=_now() - timedelta(minutes=1),
                read=False,
            ),
            models.Notification(
                type="system",
                msg="CAM-CQ-02 went offline",
                at=_now() - timedelta(hours=1),
                read=False,
            ),
            models.Notification(
                type="override",
                msg="Supervisor reviewed VIO-2026-00143",
                at=_now() - timedelta(hours=2),
                read=True,
            ),
        ]
    )


_SERVICES = [
    ("AI Detection Pipeline", "operational", "YOLO + DeepStream", "99.97%", "42ms", ""),
    ("Evidence Storage", "operational", "Local evidence store (dev)", "99.99%", "", "2.4 TB / 10 TB"),
    ("Database", "operational", "SQLite (dev)", "99.99%", "3ms", ""),
    ("Plate Recognition (ANPR)", "operational", "OCR engine v3.2", "99.92%", "85ms", ""),
    ("Network Gateway", "degraded", "High latency detected", "98.4%", "210ms", ""),
    ("Backup System", "operational", "Last backup 2h ago", "99.95%", "", "1.8 TB"),
]


def _seed_services(db: Session) -> None:
    for name, status, detail, uptime, latency, usage in _SERVICES:
        existing = (
            db.query(models.Service).filter(models.Service.name == name).one_or_none()
        )
        if existing is None:
            db.add(
                models.Service(
                    name=name,
                    status=status,
                    detail=detail,
                    uptime=uptime,
                    latency=latency,
                    usage=usage,
                )
            )


def _seed_system_status(db: Session) -> None:
    if db.query(models.SystemStatus).count() == 0:
        db.add(
            models.SystemStatus(
                status="ok",
                detail={"cpu": 34, "memory": 61, "disk": 24, "pipeline": "running"},
            )
        )
