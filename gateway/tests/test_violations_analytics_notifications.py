"""Coverage for the violations / analytics / notifications routers.

Same conventions as test_review_gateway.py: temp SQLite + env vars set BEFORE
the first gateway import (config loads at first import, so when the full suite
runs and test_review_gateway.py already pinned the settings, the guard below
skips and this module shares that DB — every assertion here is therefore
DELTA- or fixture-scoped, never an absolute row count).

Covers the four task-mandated areas:
  * privilege matrix — every review transition x every role/privilege combo
  * history APPEND (never client-replaced; forged reviewer fields ignored)
  * audit rows written server-side for every review change (and chain intact)
  * analytics semantics (window buckets, byType %, hourly histogram) on data
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

# Only pin fresh env when this module is the FIRST gateway importer (standalone
# run); in a full-suite run test_review_gateway.py sorts earlier and already
# loaded gateway.config, making these env vars inert.
if "GWREV_DB_URL" not in os.environ:
    _TMP = tempfile.mkdtemp(prefix="revgw_vtest_")
    os.environ["GWREV_DB_URL"] = f"sqlite:///{pathlib.Path(_TMP, 't.db').as_posix()}"
    os.environ["GWREV_JWT_SECRET"] = str(pathlib.Path(_TMP, "secret.bin"))
    os.environ["GWREV_EVIDENCE_DIR"] = str(pathlib.Path(_TMP, "ev"))
os.environ.setdefault("GWREV_SEED", "1")
os.environ.setdefault("GWREV_SEED_PASSWORD", "review1234")

from fastapi.testclient import TestClient  # noqa: E402

from gateway import audit, models  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.db import SessionLocal  # noqa: E402
from gateway.security import hash_password  # noqa: E402

client = TestClient(create_app())

_PW = "review1234"
_OLD = datetime(2025, 12, 1, 12, 0, 0, tzinfo=timezone.utc)  # outside all windows


def _login(username: str, password: str = _PW) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _auth(username: str) -> dict:
    return _h(_login(username)["accessToken"])


# ---------------------------------------------------------------------------
# Direct-DB fixture helpers (fast; no bcrypt where avoidable)
# ---------------------------------------------------------------------------
def _mk_violation(db, vid: str, *, vtype: str = "MatrixTest",
                  date: datetime = _OLD, history: list | None = None,
                  screenshot_url: str = "violations/fixture/shot.jpg") -> None:
    """Fixture case. Carries a screenshot by default because a rack-ingested
    violation ALWAYS ships evidence — and PATCH .../review refuses to approve
    a case with none (an approval with no evidence can never be defended)."""
    if db.get(models.Violation, vid) is None:
        db.add(models.Violation(id=vid, type=vtype, date=date,
                                history=history or [],
                                screenshot_url=screenshot_url))


def _mk_review(db, vid: str, status: str, *, by: str = "Seeder",
               notes: str = "seeded") -> None:
    if db.get(models.ViolationReview, vid) is None:
        db.add(models.ViolationReview(
            violation_id=vid, status=status, reviewed_by=by,
            reviewed_at=datetime.now(timezone.utc), notes=notes,
            pinned=False,
            history=[{"action": status, "by": by, "at": "2025-12-01T12:30:00+00:00",
                      "notes": notes}],
        ))


def _ensure_user(db, username: str, privileges: dict, display_name: str) -> None:
    exists = (db.query(models.User)
              .filter(models.User.username == username).one_or_none())
    if exists is None:
        db.add(models.User(username=username, password_hash=hash_password(_PW),
                           display_name=display_name, role="officer",
                           privileges=privileges, active=True))


def _review_status(vid: str) -> str:
    db = SessionLocal()
    try:
        r = db.get(models.ViolationReview, vid)
        return (r.status if r is not None else None) or "pending"
    finally:
        db.close()


def _audit_rows(min_seq: int = 0) -> list:
    db = SessionLocal()
    try:
        return (db.query(models.AuditLog)
                .filter(models.AuditLog.seq > min_seq)
                .order_by(models.AuditLog.seq.asc()).all())
    finally:
        db.close()


def _audit_head_seq() -> int:
    db = SessionLocal()
    try:
        return audit.head(db)["seq"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth is mandatory on every surface this module owns
# ---------------------------------------------------------------------------
def test_endpoints_require_auth():
    for method, path in (
        ("GET", "/violations"),
        ("GET", "/violations/VIO-2026-00147/history"),
        ("PATCH", "/violations/VIO-2026-00147/review"),
        ("GET", "/analytics"),
        ("GET", "/notifications"),
        ("PATCH", "/notifications/1"),
        ("POST", "/notifications/mark-all-read"),
    ):
        r = client.request(method, path, json={} if method != "GET" else None)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        assert r.json()["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# GET /violations — LEFT JOIN shape matching main.js db:get-violations
# ---------------------------------------------------------------------------
def test_violations_list_shape_join_and_order():
    h = _auth("officer")
    r = client.get("/violations", headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    rows = j["rows"]
    by_id = {row["id"]: row for row in rows}
    assert "VIO-2026-00147" in by_id and "VIO-2026-00143" in by_id

    # Every field name the renderer reads (v.* + the review aliases).
    expected_fields = {
        "id", "type", "speed", "speed_limit", "plate", "vehicle", "location",
        "gps_lat", "gps_lng", "cameras", "camera", "date", "confidence",
        "weather", "ai_summary", "status", "notes", "pinned", "history",
        "clip_url", "raw_clip_url", "screenshot_url",
        "review_status", "reviewed_by", "reviewed_at", "review_notes",
        "review_pinned", "review_history",
    }
    assert expected_fields <= set(by_id["VIO-2026-00147"])

    # Unreviewed row: COALESCE'd review fields (status 'pending', notes '',
    # pinned false, history []) and NULL reviewed_by/reviewed_at from the JOIN.
    fresh = by_id["VIO-2026-00147"]
    assert fresh["review_status"] == "pending"
    assert fresh["reviewed_by"] is None and fresh["reviewed_at"] is None
    assert fresh["review_notes"] == "" and fresh["review_pinned"] is False
    assert fresh["review_history"] == []
    assert fresh["type"] == "Speeding" and fresh["speed"] == 78
    assert fresh["cameras"] == ["CAM-AV-07", "CAM-AV-08"]

    # Seed-reviewed row surfaces the authoritative violation_reviews record.
    done = by_id["VIO-2026-00143"]
    assert done["review_status"] == "approved"
    assert done["reviewed_by"] == "Sgt. Williams"
    assert done["review_notes"] == "Clear violation."
    assert isinstance(done["review_history"], list) and done["review_history"]

    # Newest first (non-increasing by date — robust to rows other tests add).
    dates = [row["date"] for row in rows]
    assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Privilege matrix: every transition x every role/privilege combination
# ---------------------------------------------------------------------------
# Actor -> seeded/created privilege set:
#   admin      A D R   (seed)      supervisor  A D R (seed)
#   officer    A D -   (seed)      mx_approve  A - -
#   mx_revise  - - R               mx_nopriv   - - -
_TRANSITIONS = [
    ("pending", "approved"),
    ("pending", "dismissed"),
    ("approved", "dismissed"),
    ("dismissed", "approved"),
    ("approved", "pending"),  # reopen — canRevise alone
]
# Explicit expectation table (True = 200, False = 403) — deliberately
# hardcoded, NOT derived from the router's own logic.
_MATRIX = {
    "admin":      [True, True, True, True, True],
    "supervisor": [True, True, True, True, True],
    "officer":    [True, True, False, False, False],
    "mx_approve": [True, False, False, False, False],
    "mx_revise":  [False, False, False, False, True],
    "mx_nopriv":  [False, False, False, False, False],
}


def test_review_privilege_matrix():
    db = SessionLocal()
    try:
        _ensure_user(db, "mx_approve", {"canApprove": True}, "Approve Only")
        _ensure_user(db, "mx_revise", {"canRevise": True}, "Revise Only")
        _ensure_user(db, "mx_nopriv", {}, "No Privileges")
        for actor in _MATRIX:
            for i, (start, _target) in enumerate(_TRANSITIONS):
                vid = f"VIO-MX-{actor}-{i}"
                _mk_violation(db, vid)
                if start != "pending":
                    _mk_review(db, vid, start)
        db.commit()
    finally:
        db.close()

    tokens = {actor: _auth(actor) for actor in _MATRIX}

    for actor, expectations in _MATRIX.items():
        for i, ((start, target), expect_ok) in enumerate(
            zip(_TRANSITIONS, expectations)
        ):
            vid = f"VIO-MX-{actor}-{i}"
            r = client.patch(
                f"/violations/{vid}/review",
                headers=tokens[actor],
                json={"status": target},
            )
            label = f"{actor}: {start}->{target}"
            if expect_ok:
                assert r.status_code == 200, f"{label}: {r.status_code} {r.text}"
                body = r.json()
                assert body["ok"] is True and body["changed"] is True
                assert body["row"]["status"] == target
                assert _review_status(vid) == target, label
            else:
                assert r.status_code == 403, f"{label}: {r.status_code} {r.text}"
                assert r.json()["code"] == "forbidden"
                # A denied transition must not have touched the review.
                assert _review_status(vid) == start, label


def test_review_status_normalised_and_validated():
    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-VAL-1")
        db.commit()
    finally:
        db.close()
    h = _auth("supervisor")
    # Case/whitespace-insensitive status.
    r = client.patch("/violations/VIO-VAL-1/review", headers=h,
                     json={"status": "  APPROVED "})
    assert r.status_code == 200 and r.json()["row"]["status"] == "approved"
    # Unknown status -> 400 with the app error shape.
    bad = client.patch("/violations/VIO-VAL-1/review", headers=h,
                       json={"status": "banana"})
    assert bad.status_code == 400
    assert set(bad.json()) >= {"code", "message", "retryable"}
    # Unknown violation -> 404 not_found.
    missing = client.patch("/violations/VIO-DOES-NOT-EXIST/review", headers=h,
                           json={"status": "approved"})
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert client.get("/violations/VIO-DOES-NOT-EXIST/history",
                      headers=h).status_code == 404


# ---------------------------------------------------------------------------
# Server-side reviewed_by/reviewed_at + history APPEND (never client-replaced)
# ---------------------------------------------------------------------------
def test_review_server_sets_reviewer_and_ignores_forged_fields():
    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-FORGE-1")
        db.commit()
    finally:
        db.close()
    h = _auth("officer")  # display name "Cpl. James"
    before = datetime.now(timezone.utc)
    r = client.patch(
        "/violations/VIO-FORGE-1/review",
        headers=h,
        json={
            "status": "approved",
            "notes": "legit note",
            # Forged fields — all must be ignored (permissive schema tolerates
            # the keys; the handler never reads them).
            "reviewed_by": "Hacker McForge",
            "reviewed_at": "1999-01-01T00:00:00Z",
            "history": [{"action": "fabricated", "by": "Hacker"}],
        },
    )
    assert r.status_code == 200, r.text
    row = r.json()["row"]
    assert row["reviewed_by"] == "Cpl. James"  # token user's display name
    reviewed_at = datetime.fromisoformat(row["reviewed_at"])
    assert abs((reviewed_at - before).total_seconds()) < 120  # server clock
    # History was APPENDED by the server: exactly one entry, not the client's.
    assert len(row["history"]) == 1
    assert row["history"][0]["action"] == "approved"
    assert row["history"][0]["by"] == "Cpl. James"
    assert all(e.get("action") != "fabricated" for e in row["history"])


def test_review_history_appends_across_changes():
    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-HIST-1", history=[
            {"action": "flagged", "by": "AI System",
             "at": "2025-12-01T12:00:00Z", "notes": "auto"},
        ])
        db.commit()
    finally:
        db.close()
    sup = _auth("supervisor")   # Sgt. Williams — canApprove/Dismiss/Revise
    adm = _auth("admin")        # Administrator — all privileges

    r1 = client.patch("/violations/VIO-HIST-1/review", headers=sup,
                      json={"status": "approved", "notes": "first"})
    h1 = r1.json()["row"]["history"]
    assert [e["action"] for e in h1] == ["approved"]
    assert h1[0]["by"] == "Sgt. Williams" and h1[0]["from"] == "pending"

    # Second change (revise) APPENDS — entry 1 must survive verbatim.
    r2 = client.patch("/violations/VIO-HIST-1/review", headers=adm,
                      json={"status": "dismissed"})
    h2 = r2.json()["row"]["history"]
    assert len(h2) == 2 and h2[0] == h1[0]
    assert h2[1]["action"] == "dismissed" and h2[1]["by"] == "Administrator"
    assert h2[1]["from"] == "approved"

    # Notes-only edit appends note_updated.
    r3 = client.patch("/violations/VIO-HIST-1/review", headers=adm,
                      json={"notes": "amended detail"})
    h3 = r3.json()["row"]["history"]
    assert len(h3) == 3 and h3[:2] == h2[:2]
    assert h3[2]["action"] == "note_updated"

    # Pin appends its own entry.
    r4 = client.patch("/violations/VIO-HIST-1/review", headers=adm,
                      json={"pinned": True})
    h4 = r4.json()["row"]["history"]
    assert len(h4) == 4 and h4[3]["action"] == "pinned"
    assert r4.json()["row"]["pinned"] is True

    # /history returns full provenance: violation history + review history.
    full = client.get("/violations/VIO-HIST-1/history", headers=adm).json()
    assert full["ok"] is True and full["violationId"] == "VIO-HIST-1"
    actions = [e["action"] for e in full["history"]]
    assert actions == ["flagged", "approved", "dismissed", "note_updated", "pinned"]


# ---------------------------------------------------------------------------
# Audit rows: one server-side row per review change, chain stays intact
# ---------------------------------------------------------------------------
def test_review_changes_write_audit_rows_and_chain_verifies():
    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-AUD-1")
        db.commit()
    finally:
        db.close()
    sup = _auth("supervisor")
    base = _audit_head_seq()  # logins above already audited; start from here

    steps = [
        ({"status": "approved"}, "review_approved", "AUD-RAP"),
        ({"status": "dismissed"}, "review_dismissed", "AUD-RDI"),
        ({"status": "pending"}, "review_reopened", "AUD-RRE"),
        ({"pinned": True}, "pinned", "AUD-RPN"),
        ({"notes": "audit trail note"}, "review_notes", "AUD-RNT"),
    ]
    for body, expected_action, prefix in steps:
        seq_before = _audit_head_seq()
        r = client.patch("/violations/VIO-AUD-1/review", headers=sup, json=body)
        assert r.status_code == 200, f"{body}: {r.text}"
        new_rows = _audit_rows(min_seq=seq_before)
        assert len(new_rows) == 1, f"{body} wrote {len(new_rows)} audit rows"
        row = new_rows[0]
        assert row.action == expected_action
        assert row.id.startswith(prefix)
        assert row.officer == "supervisor"          # username from the TOKEN
        assert row.violation_id == "VIO-AUD-1"
        assert "from" in row.detail and "to" in row.detail

    rows = _audit_rows(min_seq=base)
    assert [r.action for r in rows] == [a for _, a, _ in steps]

    # The whole chain (including these rows) still verifies.
    db = SessionLocal()
    try:
        v = audit.verify_chain(db)
    finally:
        db.close()
    assert v["ok"] is True and v["first_broken_seq"] is None


def test_review_noop_writes_no_audit_row():
    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-NOOP-1")
        _mk_review(db, "VIO-NOOP-1", "approved", notes="as-is")
        db.commit()
    finally:
        db.close()
    sup = _auth("supervisor")
    seq_before = _audit_head_seq()
    # Same status, same notes, same pinned -> nothing to write or audit.
    r = client.patch("/violations/VIO-NOOP-1/review", headers=sup,
                     json={"status": "approved", "notes": "as-is",
                           "pinned": False})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["changed"] is False
    assert _audit_head_seq() == seq_before
    # A denied (403) attempt must not audit either.
    off = _auth("officer")
    seq_before = _audit_head_seq()
    denied = client.patch("/violations/VIO-NOOP-1/review", headers=off,
                          json={"status": "dismissed"})
    assert denied.status_code == 403
    assert _audit_head_seq() == seq_before


# ---------------------------------------------------------------------------
# Analytics — window buckets, byType %, hourly histogram (delta-based so the
# shared suite DB never breaks the math)
# ---------------------------------------------------------------------------
def test_analytics_shape_and_windows():
    from gateway.routers.analytics import _local_midnight_utc

    h = _auth("supervisor")
    a0 = client.get("/analytics", headers=h)
    assert a0.status_code == 200, a0.text
    d0 = a0.json()["data"]
    assert set(d0) == {"today", "week", "month", "byType", "hourly"}
    for bucket in ("today", "week", "month"):
        assert set(d0[bucket]) == {"total", "approved", "dismissed", "pending"}
    assert len(d0["hourly"]) == 24

    now = datetime.now(timezone.utc)
    today_start = _local_midnight_utc()
    db = SessionLocal()
    try:
        # today window (and thus week + month + hourly)
        _mk_violation(db, "VIO-AN-TODAY", vtype="AnalyticsTest", date=now)
        # inside week window only (3 days back), pre-approved
        _mk_violation(db, "VIO-AN-WEEK", vtype="AnalyticsTest",
                      date=today_start - timedelta(days=3))
        _mk_review(db, "VIO-AN-WEEK", "approved")
        # inside month window only (20 days back), pre-dismissed
        _mk_violation(db, "VIO-AN-MONTH", vtype="AnalyticsTest",
                      date=today_start - timedelta(days=20))
        _mk_review(db, "VIO-AN-MONTH", "dismissed")
        # outside every window (40 days back) — must not move any bucket
        _mk_violation(db, "VIO-AN-OLD", vtype="AnalyticsTest",
                      date=today_start - timedelta(days=40))
        db.commit()
    finally:
        db.close()

    d1 = client.get("/analytics", headers=h).json()["data"]

    # today: exactly the one new pending violation.
    assert d1["today"]["total"] == d0["today"]["total"] + 1
    assert d1["today"]["pending"] == d0["today"]["pending"] + 1
    assert d1["today"]["approved"] == d0["today"]["approved"]
    assert d1["today"]["dismissed"] == d0["today"]["dismissed"]
    # week: today + the 3-day-old approved one.
    assert d1["week"]["total"] == d0["week"]["total"] + 2
    assert d1["week"]["pending"] == d0["week"]["pending"] + 1
    assert d1["week"]["approved"] == d0["week"]["approved"] + 1
    assert d1["week"]["dismissed"] == d0["week"]["dismissed"]
    # month: all three in-window rows; the 40-day row moved nothing.
    assert d1["month"]["total"] == d0["month"]["total"] + 3
    assert d1["month"]["pending"] == d0["month"]["pending"] + 1
    assert d1["month"]["approved"] == d0["month"]["approved"] + 1
    assert d1["month"]["dismissed"] == d0["month"]["dismissed"] + 1

    # hourly: today's violation lands in its (stored-UTC) hour slot.
    assert sum(d1["hourly"]) == sum(d0["hourly"]) + 1
    assert d1["hourly"][now.hour] == d0["hourly"][now.hour] + 1

    # byType: integer percentages over ALL violations, new type present,
    # seeded types present, and the rounded shares still sum to ~100.
    by_type = d1["byType"]
    assert "AnalyticsTest" in by_type
    assert {"Speeding", "Reckless Driving", "Illegal Parking"} <= set(by_type)
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in by_type.values())
    assert 96 <= sum(by_type.values()) <= 104  # Math.round drift only


def test_analytics_js_round_parity():
    # main.js used Math.round (half UP); Python's round() is banker's — the
    # helper must match JS so percentage splits are byte-identical.
    from gateway.routers.analytics import _js_round

    assert _js_round(0.5) == 1 and round(0.5) == 0  # the divergence being fixed
    assert _js_round(2.5) == 3
    assert _js_round(2.4) == 2
    assert _js_round(100 * 2 / 7) == 29  # 28.57 -> 29
    assert _js_round(100 * 1 / 7) == 14  # 14.28 -> 14


# ---------------------------------------------------------------------------
# Notifications: list (limit 50, newest first), mark-read, mark-all-read
# ---------------------------------------------------------------------------
def test_notifications_list_newest_first_limit_50():
    h = _auth("officer")
    r = client.get("/notifications", headers=h)
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows, "seed should provide notifications"
    assert {"id", "type", "msg", "at", "read"} <= set(rows[0])
    ats = [row["at"] for row in rows]
    assert ats == sorted(ats, reverse=True)  # newest first

    # Bulk-insert past the cap -> exactly 50 come back, newest first.
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.add_all([
            models.Notification(type="system", msg=f"bulk {i}",
                                at=now - timedelta(seconds=i), read=False)
            for i in range(55)
        ])
        db.commit()
    finally:
        db.close()
    rows = client.get("/notifications", headers=h).json()["rows"]
    assert len(rows) == 50
    ats = [row["at"] for row in rows]
    assert ats == sorted(ats, reverse=True)
    assert rows[0]["msg"] == "bulk 0"  # the newest bulk row leads


def test_notification_mark_read_and_unread():
    h = _auth("officer")
    db = SessionLocal()
    try:
        n = models.Notification(type="violation", msg="mark-read target",
                                at=datetime.now(timezone.utc), read=False)
        db.add(n)
        db.commit()
        nid = n.id
    finally:
        db.close()

    # Legacy IPC sent no payload -> empty body means "mark read".
    r = client.patch(f"/notifications/{nid}", headers=h)
    assert r.status_code == 200
    assert r.json()["row"]["read"] is True
    # Explicit unread round-trip.
    r = client.patch(f"/notifications/{nid}", headers=h, json={"read": False})
    assert r.json()["row"]["read"] is False
    # Unknown id -> 404 with the app error shape.
    missing = client.patch("/notifications/99999999", headers=h)
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


def test_notifications_mark_all_read():
    h = _auth("officer")
    # Read state is PER USER, so "unread" means unread BY THIS USER — not the
    # legacy global notifications.read column. mark-all-read covers EVERY
    # notification, not just the 50-row window GET /notifications returns.
    db = SessionLocal()
    try:
        uid = db.query(models.User).filter(models.User.username == "officer").one().id
        total = db.query(models.Notification).count()
        already = (db.query(models.NotificationRead)
                   .filter(models.NotificationRead.user_id == uid)
                   .count())
    finally:
        db.close()
    unread_before = total - already
    assert unread_before > 0  # prior tests left rows this user has not read

    seq_before = _audit_head_seq()
    r = client.post("/notifications/mark-all-read", headers=h)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "updated": unread_before}

    rows = client.get("/notifications", headers=h).json()["rows"]
    assert all(row["read"] is True for row in rows)
    # Idempotent: nothing left to update.
    again = client.post("/notifications/mark-all-read", headers=h)
    assert again.json()["updated"] == 0
    # Inbox housekeeping is deliberately NOT audited.
    assert _audit_head_seq() == seq_before


def test_notification_read_state_is_per_user():
    """One reviewer opening a notification must not hide it from another.

    The notifications table has a single global `read` column; read state is
    tracked per (notification, user) instead.
    """
    db = SessionLocal()
    try:
        n = models.Notification(type="info", msg="per-user read isolation probe")
        db.add(n)
        db.commit()
        nid = n.id
    finally:
        db.close()

    officer = _auth("officer")
    supervisor = _auth("supervisor")

    def _seen(headers) -> bool | None:
        for row in client.get("/notifications", headers=headers).json()["rows"]:
            if row["id"] == nid:
                return row["read"]
        return None

    assert _seen(officer) is False
    assert _seen(supervisor) is False

    assert client.patch(f"/notifications/{nid}", headers=officer).status_code == 200
    assert _seen(officer) is True
    assert _seen(supervisor) is False, "another reviewer's inbox was silently marked read"

    # ...and marking everything read for one user leaves the other untouched.
    client.post("/notifications/mark-all-read", headers=officer)
    assert _seen(supervisor) is False
