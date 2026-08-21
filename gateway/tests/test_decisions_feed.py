"""Coverage for the read-only review-decision feed (GET /decisions/feed —
see gateway_api_contract.md "Review-gateway decision feed" and
routers/decisions.py).

Same conventions as the other router test modules: only pin fresh env when
this module is the FIRST gateway importer (so a full-suite run shares the DB
that test_review_gateway.py already bootstrapped); assertions are therefore
delta-scoped / cursor-scoped, never an absolute row count.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from datetime import datetime, timezone

if "GWREV_DB_URL" not in os.environ:
    _TMP = tempfile.mkdtemp(prefix="revgw_decisions_test_")
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
            plate="SV-FEED-1",
            vehicle="Test Vehicle",
            location="Test Location",
            gps_lat=13.15,
            gps_lng=-61.2,
            camera="CAM-TEST-1",
            date=datetime(2026, 3, 20, 9, 0, 0, tzinfo=timezone.utc),
            clip_url="",
            raw_clip_url="",
            # A case with no evidence at all cannot be approved (see
            # PATCH /violations/{id}/review), so fixtures carry a screenshot.
            screenshot_url="violations/fixture/shot.jpg",
            citable=None,
            gate_reason="",
        )
        defaults.update(kwargs)
        db.add(models.Violation(**defaults))


def _decide(vid: str, status: str, notes: str | None = None, auth: dict | None = None) -> None:
    h = auth or _auth("supervisor")
    body: dict = {"status": status}
    if notes is not None:
        body["notes"] = notes
    r = client.patch(f"/violations/{vid}/review", headers=h, json=body)
    assert r.status_code == 200, r.text


def _max_event_id() -> int:
    """A cursor before any of this module's own rows, so each test's feed
    query only ever sees rows it itself creates."""
    db = SessionLocal()
    try:
        row = (
            db.query(models.DecisionOutbox)
            .order_by(models.DecisionOutbox.id.desc())
            .first()
        )
        return row.id if row is not None else 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Privilege gate
# ---------------------------------------------------------------------------
def test_officer_without_can_export_gets_403():
    r = client.get("/decisions/feed", headers=_auth("officer"))
    assert r.status_code == 403, r.text


def test_supervisor_with_can_export_gets_200():
    r = client.get("/decisions/feed", headers=_auth("supervisor"))
    assert r.status_code == 200, r.text
    assert "items" in r.json()


def test_admin_with_can_export_gets_200():
    r = client.get("/decisions/feed", headers=_auth("admin"))
    assert r.status_code == 200, r.text
    assert "items" in r.json()


def test_no_bearer_gets_401():
    r = client.get("/decisions/feed")
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# Empty feed: no rows past a cursor at (or beyond) the current head.
# ---------------------------------------------------------------------------
def test_empty_feed_returns_no_items_and_no_next_event_id():
    since = _max_event_id() + 10_000_000  # well beyond anything ever written
    r = client.get(f"/decisions/feed?since={since}", headers=_auth("supervisor"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert "nextEventId" not in body


# ---------------------------------------------------------------------------
# All three decision kinds appear, payload passthrough, cursor pagination.
# ---------------------------------------------------------------------------
def test_all_decision_kinds_appear_with_payload_passthrough_and_cursor():
    db = SessionLocal()
    try:
        _mk_violation(
            db,
            "VIO-FEED-A",
            citable=True,
            gate_reason="gate: citation class, certified basis",
            clip_url="https://evidence/clip.mp4",
        )
        _mk_violation(db, "VIO-FEED-B")
        db.commit()
    finally:
        db.close()

    start = _max_event_id()
    sup = _auth("supervisor")

    # approved (VIO-FEED-A)
    _decide("VIO-FEED-A", "approved", notes="clear violation", auth=sup)
    # dismissed (VIO-FEED-B)
    _decide("VIO-FEED-B", "dismissed", auth=sup)
    # reopened: approve then send back to pending (VIO-FEED-B)
    _decide("VIO-FEED-B", "approved", auth=sup)
    _decide("VIO-FEED-B", "pending", auth=sup)

    # ---- Page 1: since=start, limit=3 ----
    r1 = client.get(f"/decisions/feed?since={start}&limit=3", headers=sup)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    items1 = body1["items"]
    assert len(items1) == 3
    assert [i["decision"] for i in items1] == ["approved", "dismissed", "approved"]
    assert "nextEventId" in body1  # page was full -> more may exist
    assert body1["nextEventId"] == items1[-1]["eventId"]
    # ids strictly ascending
    ids1 = [i["eventId"] for i in items1]
    assert ids1 == sorted(ids1)
    assert len(set(ids1)) == len(ids1)

    approved_item = items1[0]
    assert approved_item["violationId"] == "VIO-FEED-A"
    assert approved_item["reviewedBy"] == "Sgt. Williams"
    assert approved_item["reviewedAtUtc"]
    assert approved_item["notes"] == "clear violation"
    v = approved_item["violation"]
    assert v["plate"] == "SV-FEED-1"
    assert v["type"] == "Speeding"
    assert v["citable"] is True
    assert v["gateReason"] == "gate: citation class, certified basis"
    kinds = {e["kind"] for e in v["evidence"]}
    assert "clip" in kinds

    dismissed_item = items1[1]
    assert dismissed_item["violationId"] == "VIO-FEED-B"
    assert dismissed_item["decision"] == "dismissed"

    # ---- Page 2: since=nextEventId from page 1 ----
    r2 = client.get(
        f"/decisions/feed?since={body1['nextEventId']}&limit=3", headers=sup
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    items2 = body2["items"]
    assert len(items2) == 1
    assert items2[0]["decision"] == "reopened"
    assert items2[0]["violationId"] == "VIO-FEED-B"
    # Under-full page -> no more rows -> no nextEventId.
    assert "nextEventId" not in body2

    # No overlap between the two pages.
    assert set(ids1).isdisjoint({i["eventId"] for i in items2})


# ---------------------------------------------------------------------------
# Limit clamp / bad param validation
# ---------------------------------------------------------------------------
def test_limit_over_max_is_rejected():
    r = client.get("/decisions/feed?limit=1001", headers=_auth("supervisor"))
    assert r.status_code == 400, r.text


def test_limit_zero_is_rejected():
    r = client.get("/decisions/feed?limit=0", headers=_auth("supervisor"))
    assert r.status_code == 400, r.text


def test_negative_since_is_rejected():
    r = client.get("/decisions/feed?since=-1", headers=_auth("supervisor"))
    assert r.status_code == 400, r.text


def test_limit_at_max_is_accepted():
    r = client.get("/decisions/feed?limit=1000", headers=_auth("supervisor"))
    assert r.status_code == 200, r.text
