"""Coverage for the transactional decision outbox (citation-lifecycle bridge
step 1 — see gateway_api_contract.md "Camera citations — the review->service
bridge" and models.DecisionOutbox's own docstring for the append-only /
same-txn / event-id contract this module verifies).

Same conventions as the other router test modules: only pin fresh env when
this module is the FIRST gateway importer (so a full-suite run shares the DB
that test_review_gateway.py already bootstrapped); assertions are therefore
delta-scoped, never an absolute row count.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from datetime import datetime, timezone

if "GWREV_DB_URL" not in os.environ:
    _TMP = tempfile.mkdtemp(prefix="revgw_outbox_test_")
    os.environ["GWREV_DB_URL"] = f"sqlite:///{pathlib.Path(_TMP, 't.db').as_posix()}"
    os.environ["GWREV_JWT_SECRET"] = str(pathlib.Path(_TMP, "secret.bin"))
    os.environ["GWREV_EVIDENCE_DIR"] = str(pathlib.Path(_TMP, "ev"))
os.environ.setdefault("GWREV_SEED", "1")
os.environ.setdefault("GWREV_SEED_PASSWORD", "review1234")

from fastapi.testclient import TestClient  # noqa: E402

from gateway import models  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.db import SessionLocal  # noqa: E402

client = TestClient(create_app())

_PW = "review1234"


def _login(username: str, password: str = _PW) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _auth(username: str) -> dict:
    return _h(_login(username)["accessToken"])


def _mk_violation(db, vid: str, **kwargs) -> None:
    if db.get(models.Violation, vid) is None:
        defaults = dict(
            id=vid,
            type="Speeding",
            speed=70,
            speed_limit=50,
            plate="SV-OUTB-1",
            vehicle="Test Vehicle",
            location="Test Location",
            gps_lat=13.15,
            gps_lng=-61.2,
            camera="CAM-TEST-1",
            date=datetime(2026, 3, 20, 9, 0, 0, tzinfo=timezone.utc),
            clip_url="",
            raw_clip_url="",
            screenshot_url="",
            citable=None,
            gate_reason="",
        )
        defaults.update(kwargs)
        db.add(models.Violation(**defaults))


def _outbox_rows(violation_id: str) -> list:
    db = SessionLocal()
    try:
        return (
            db.query(models.DecisionOutbox)
            .filter(models.DecisionOutbox.violation_id == violation_id)
            .order_by(models.DecisionOutbox.id.asc())
            .all()
        )
    finally:
        db.close()


def _outbox_count() -> int:
    db = SessionLocal()
    try:
        return db.query(models.DecisionOutbox).count()
    finally:
        db.close()


def _review_status(vid: str) -> str:
    db = SessionLocal()
    try:
        r = db.get(models.ViolationReview, vid)
        return (r.status if r is not None else None) or "pending"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Status change writes exactly one outbox row with correct decision + payload
# ---------------------------------------------------------------------------
def test_approve_writes_one_outbox_row_with_payload():
    db = SessionLocal()
    try:
        _mk_violation(
            db,
            "VIO-OUTB-APPROVE",
            citable=True,
            gate_reason="gate: citation class, certified basis",
            clip_url="https://evidence/clip.mp4",
            raw_clip_url="https://evidence/raw.mp4",
            screenshot_url="",
        )
        db.commit()
    finally:
        db.close()

    h = _auth("supervisor")
    r = client.patch(
        "/violations/VIO-OUTB-APPROVE/review",
        headers=h,
        json={"status": "approved", "notes": "clear violation"},
    )
    assert r.status_code == 200, r.text

    rows = _outbox_rows("VIO-OUTB-APPROVE")
    assert len(rows) == 1
    row = rows[0]
    assert row.decision == "approved"
    assert row.delivered_at is None
    assert row.attempts == 0
    assert row.last_error == ""

    p = row.payload
    assert p["violationId"] == "VIO-OUTB-APPROVE"
    assert p["decision"] == "approved"
    assert p["reviewedBy"] == "Sgt. Williams"
    assert p["reviewNotes"] == "clear violation"
    assert p["reviewedAtUtc"]  # ISO string, server clock

    v = p["violation"]
    assert v["plate"] == "SV-OUTB-1"
    assert v["type"] == "Speeding"
    assert v["speedMph"] == 70
    assert v["speedLimitMph"] == 50
    assert v["camera"] == "CAM-TEST-1"
    assert v["capturedAtUtc"]
    assert v["location"] == {"lat": 13.15, "lng": -61.2, "label": "Test Location"}
    assert v["citable"] is True
    assert v["gateReason"] == "gate: citation class, certified basis"
    # Empty screenshot_url omitted; clip + raw_clip present.
    kinds = {e["kind"] for e in v["evidence"]}
    assert kinds == {"clip", "raw_clip"}
    assert {"kind": "clip", "url": "https://evidence/clip.mp4"} in v["evidence"]
    assert {"kind": "raw_clip", "url": "https://evidence/raw.mp4"} in v["evidence"]


def test_dismiss_writes_dismissed_decision_and_null_citable_passthrough():
    db = SessionLocal()
    try:
        # citable/gate_reason left at defaults (None / "") — nothing populates
        # them for this row, proving passthrough of the "unset" case too.
        _mk_violation(db, "VIO-OUTB-DISMISS")
        db.commit()
    finally:
        db.close()

    h = _auth("supervisor")
    r = client.patch(
        "/violations/VIO-OUTB-DISMISS/review",
        headers=h,
        json={"status": "dismissed"},
    )
    assert r.status_code == 200, r.text

    rows = _outbox_rows("VIO-OUTB-DISMISS")
    assert len(rows) == 1
    assert rows[0].decision == "dismissed"
    assert rows[0].payload["violation"]["citable"] is None
    assert rows[0].payload["violation"]["gateReason"] == ""
    assert rows[0].payload["violation"]["evidence"] == []  # all three urls empty


# ---------------------------------------------------------------------------
# Note-only and pin-only PATCHes write NO outbox row
# ---------------------------------------------------------------------------
def test_note_only_and_pin_only_write_no_outbox_row():
    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-OUTB-NOTEPIN")
        db.commit()
    finally:
        db.close()

    h = _auth("supervisor")
    before = _outbox_count()

    r1 = client.patch(
        "/violations/VIO-OUTB-NOTEPIN/review", headers=h, json={"notes": "just a note"}
    )
    assert r1.status_code == 200 and r1.json()["changed"] is True
    assert _outbox_count() == before

    r2 = client.patch(
        "/violations/VIO-OUTB-NOTEPIN/review", headers=h, json={"pinned": True}
    )
    assert r2.status_code == 200 and r2.json()["changed"] is True
    assert _outbox_count() == before

    assert _outbox_rows("VIO-OUTB-NOTEPIN") == []


# ---------------------------------------------------------------------------
# Re-decide transitions each append a NEW row (append-only, one per transition)
# ---------------------------------------------------------------------------
def test_redecide_transitions_append_new_rows_each_time():
    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-OUTB-REDECIDE")
        db.commit()
    finally:
        db.close()

    sup = _auth("supervisor")  # canApprove/Dismiss/Revise

    r1 = client.patch(
        "/violations/VIO-OUTB-REDECIDE/review", headers=sup, json={"status": "approved"}
    )
    assert r1.status_code == 200
    r2 = client.patch(
        "/violations/VIO-OUTB-REDECIDE/review", headers=sup, json={"status": "dismissed"}
    )
    assert r2.status_code == 200
    r3 = client.patch(
        "/violations/VIO-OUTB-REDECIDE/review", headers=sup, json={"status": "pending"}
    )
    assert r3.status_code == 200
    r4 = client.patch(
        "/violations/VIO-OUTB-REDECIDE/review", headers=sup, json={"status": "approved"}
    )
    assert r4.status_code == 200

    rows = _outbox_rows("VIO-OUTB-REDECIDE")
    assert [row.decision for row in rows] == [
        "approved",
        "dismissed",
        "reopened",
        "approved",
    ]
    # Monotonic, strictly increasing ids (the bridge event id).
    ids = [row.id for row in rows]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


# ---------------------------------------------------------------------------
# Atomicity: a failure after the review write but before commit rolls back
# BOTH the review change and the outbox row.
# ---------------------------------------------------------------------------
def test_atomic_failure_before_commit_writes_no_outbox_row_and_no_review_change():
    import pytest

    from gateway import audit as audit_module

    db = SessionLocal()
    try:
        _mk_violation(db, "VIO-OUTB-ATOMIC")
        db.commit()
    finally:
        db.close()

    h = _auth("supervisor")
    before_outbox = _outbox_count()
    assert _review_status("VIO-OUTB-ATOMIC") == "pending"

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure after review write, before commit")

    # The request-context middleware (app.py's BaseHTTPMiddleware) re-raises
    # the underlying exception past the TestClient boundary rather than
    # returning app.py's catch-all 500 JSON — the load-bearing assertion here
    # is that NOTHING committed, regardless of how the error surfaces.
    orig_record = audit_module.record
    audit_module.record = _boom
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            client.patch(
                "/violations/VIO-OUTB-ATOMIC/review",
                headers=h,
                json={"status": "approved"},
            )
    finally:
        audit_module.record = orig_record

    # Nothing persisted: no outbox row, review still pending.
    assert _outbox_count() == before_outbox
    assert _outbox_rows("VIO-OUTB-ATOMIC") == []
    assert _review_status("VIO-OUTB-ATOMIC") == "pending"

    # Sanity: the SAME violation can still be approved normally afterwards,
    # proving the failed attempt left no partial state behind.
    r = client.patch(
        "/violations/VIO-OUTB-ATOMIC/review", headers=h, json={"status": "approved"}
    )
    assert r.status_code == 200, r.text
    assert _review_status("VIO-OUTB-ATOMIC") == "approved"
    assert len(_outbox_rows("VIO-OUTB-ATOMIC")) == 1
