"""Coverage for the rack->review violation ingestion seam (see
gateway_api_contract.md "Rack->review violation ingestion" and
gateway/routers/rack_ingest.py's own contract docstring).

Same conventions as the other router test modules: only pin fresh env when
this module is the FIRST gateway importer (so a full-suite run shares the DB
that test_review_gateway.py already bootstrapped); assertions are therefore
delta-scoped, never an absolute row count. Per-test settings tweaks use
dataclasses.replace on the importing module's settings object.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import tempfile

if "GWREV_DB_URL" not in os.environ:
    _TMP = tempfile.mkdtemp(prefix="revgw_rackingest_test_")
    os.environ["GWREV_DB_URL"] = f"sqlite:///{pathlib.Path(_TMP, 't.db').as_posix()}"
    os.environ["GWREV_JWT_SECRET"] = str(pathlib.Path(_TMP, "secret.bin"))
    os.environ["GWREV_EVIDENCE_DIR"] = str(pathlib.Path(_TMP, "ev"))
os.environ.setdefault("GWREV_SEED", "1")
os.environ.setdefault("GWREV_SEED_PASSWORD", "review1234")

from fastapi.testclient import TestClient  # noqa: E402

from gateway import models  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.db import SessionLocal  # noqa: E402
from gateway.routers import rack_ingest as rack_ingest_module  # noqa: E402

client = TestClient(create_app())

_PW = "review1234"
_SECRET = "test-rack-secret-abc123"


def _login(username: str, password: str = _PW) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _auth(username: str) -> dict:
    return _h(_login(username)["accessToken"])


def _with_secret(secret: str):
    """Context manager-ish helper: patch rack_ingest_module.settings for the
    duration of the wrapped calls, matching test_bridge_worker.py /
    test_review_gateway.py's dataclasses.replace convention."""

    class _Ctx:
        def __enter__(self):
            self._orig = rack_ingest_module.settings
            rack_ingest_module.settings = dataclasses.replace(
                self._orig, rack_ingress_secret=secret
            )
            return rack_ingest_module.settings

        def __exit__(self, *exc):
            rack_ingest_module.settings = self._orig

    return _Ctx()


def _get_violation(vid: str) -> models.Violation | None:
    db = SessionLocal()
    try:
        return db.get(models.Violation, vid)
    finally:
        db.close()


_FULL_PAYLOAD = {
    "id": "V-SPD-260707-AB12CD3",
    "type": "Speeding",
    "plate": "SV-9911",
    "speedMph": 62,
    "speedLimitMph": 40,
    "camera": "CAM-AV-07",
    "cameras": ["CAM-AV-07", "CAM-AV-08"],
    "capturedAtUtc": "2026-07-07T09:15:00Z",
    "location": {"lat": 13.1339, "lng": -61.2108, "label": "Leeward Hwy, Arnos Vale"},
    "confidence": 91.5,
    "weather": "Clear",
    "citable": True,
    "gateReason": "gate: citation class, certified basis",
    "evidence": {
        "clipUrl": "https://minio.local/clip.mp4",
        "rawClipUrl": "https://minio.local/raw.mp4",
        "screenshotUrl": "https://minio.local/shot.jpg",
    },
}


# ---------------------------------------------------------------------------
# Secret guard
# ---------------------------------------------------------------------------
def test_missing_secret_header_401():
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            json={**_FULL_PAYLOAD, "id": "V-GUARD-MISSING-1"},
        )
    assert r.status_code == 401
    j = r.json()
    assert j["code"] == "unauthorized"
    assert set(j) == {"code", "message", "retryable"}
    assert _get_violation("V-GUARD-MISSING-1") is None


def test_wrong_secret_header_401():
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": "totally-wrong"},
            json={**_FULL_PAYLOAD, "id": "V-GUARD-WRONG-1"},
        )
    assert r.status_code == 401
    assert _get_violation("V-GUARD-WRONG-1") is None


def test_unprovisioned_secret_401_even_with_a_header():
    # Empty config = fail-closed, regardless of what header is presented.
    with _with_secret(""):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": "anything-at-all"},
            json={**_FULL_PAYLOAD, "id": "V-GUARD-EMPTY-1"},
        )
    assert r.status_code == 401
    assert _get_violation("V-GUARD-EMPTY-1") is None


# ---------------------------------------------------------------------------
# Happy path: full-field ingest, exact wire -> column mapping
# ---------------------------------------------------------------------------
def test_full_field_ingest_maps_fields_and_appears_pending_on_board():
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=_FULL_PAYLOAD,
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j == {"id": "V-SPD-260707-AB12CD3", "status": "pending", "duplicate": False}

    v = _get_violation("V-SPD-260707-AB12CD3")
    assert v is not None
    assert v.id == "V-SPD-260707-AB12CD3"
    assert v.type == "Speeding"
    assert v.plate == "SV-9911"
    assert v.speed == 62  # speedMph -> speed
    assert v.speed_limit == 40  # speedLimitMph -> speed_limit
    assert v.camera == "CAM-AV-07"
    assert v.cameras == ["CAM-AV-07", "CAM-AV-08"]
    assert v.date.isoformat().startswith("2026-07-07T09:15:00")  # capturedAtUtc -> date
    assert v.location == "Leeward Hwy, Arnos Vale"  # location.label -> location
    assert v.gps_lat == 13.1339  # location.lat -> gps_lat
    assert v.gps_lng == -61.2108  # location.lng -> gps_lng
    assert v.confidence == 91.5
    assert v.weather == "Clear"
    assert v.ai_summary == ""
    assert v.status == "pending"
    assert v.citable is True
    assert v.gate_reason == "gate: citation class, certified basis"
    assert v.clip_url == "https://minio.local/clip.mp4"
    assert v.raw_clip_url == "https://minio.local/raw.mp4"
    assert v.screenshot_url == "https://minio.local/shot.jpg"
    assert v.history and v.history[0]["action"] == "ingested_from_rack"

    # Shows up on the reviewer board (GET /violations) as pending.
    h = _auth("officer")
    board = client.get("/violations", headers=h)
    assert board.status_code == 200
    rows = {row["id"]: row for row in board.json()["rows"]}
    assert "V-SPD-260707-AB12CD3" in rows
    row = rows["V-SPD-260707-AB12CD3"]
    assert row["status"] == "pending"
    assert row["review_status"] == "pending"
    assert row["speed"] == 62
    assert row["speed_limit"] == 40
    assert row["gps_lat"] == 13.1339
    assert row["gps_lng"] == -61.2108
    assert row["clip_url"] == "https://minio.local/clip.mp4"


def test_legacy_violation_uid_format_accepted():
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json={**_FULL_PAYLOAD, "id": "V-LEGACY-42"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "V-LEGACY-42"
    assert _get_violation("V-LEGACY-42") is not None


# ---------------------------------------------------------------------------
# Minimal-field ingest
# ---------------------------------------------------------------------------
def test_minimal_field_ingest_defaults_and_none_citable():
    minimal = {
        "id": "V-MIN-260707-XYZ0001",
        "type": "Reckless Driving",
        "capturedAtUtc": "2026-07-07T10:00:00Z",
    }
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=minimal,
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "V-MIN-260707-XYZ0001", "status": "pending", "duplicate": False}

    v = _get_violation("V-MIN-260707-XYZ0001")
    assert v is not None
    assert v.type == "Reckless Driving"
    assert v.speed is None
    assert v.speed_limit is None
    assert v.plate == ""
    assert v.location == ""
    assert v.gps_lat is None
    assert v.gps_lng is None
    assert v.cameras == []
    assert v.camera == ""
    assert v.confidence is None
    assert v.weather == ""
    assert v.citable is None  # absent in payload -> stored as None, not rejected
    assert v.gate_reason == ""
    assert v.clip_url == ""
    assert v.raw_clip_url == ""
    assert v.screenshot_url == ""
    assert v.status == "pending"


# ---------------------------------------------------------------------------
# Duplicate id: first-write-wins, no overwrite
# ---------------------------------------------------------------------------
def test_duplicate_id_returns_duplicate_true_and_does_not_overwrite():
    first = {**_FULL_PAYLOAD, "id": "V-DUP-260707-1111111"}
    with _with_secret(_SECRET):
        r1 = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=first,
        )
    assert r1.status_code == 200, r1.text
    assert r1.json()["duplicate"] is False

    # Second payload differs (speed, plate, type) — must NOT overwrite.
    second = {
        **_FULL_PAYLOAD,
        "id": "V-DUP-260707-1111111",
        "speedMph": 999,
        "plate": "DIFFERENT-PLATE",
        "type": "Illegal Parking",
    }
    with _with_secret(_SECRET):
        r2 = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=second,
        )
    assert r2.status_code == 200, r2.text
    assert r2.json() == {
        "id": "V-DUP-260707-1111111",
        "status": "pending",
        "duplicate": True,
    }

    v = _get_violation("V-DUP-260707-1111111")
    assert v is not None
    # Byte-unchanged from the FIRST payload.
    assert v.speed == 62
    assert v.plate == "SV-9911"
    assert v.type == "Speeding"


# ---------------------------------------------------------------------------
# Validation: bad capturedAtUtc, missing id/type
# ---------------------------------------------------------------------------
def test_bad_captured_at_utc_400():
    bad = {**_FULL_PAYLOAD, "id": "V-BAD-DATE-1", "capturedAtUtc": "not-a-date"}
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=bad,
        )
    assert r.status_code == 400
    assert _get_violation("V-BAD-DATE-1") is None


def test_missing_id_400():
    body = {k: v for k, v in _FULL_PAYLOAD.items() if k != "id"}
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=body,
        )
    assert r.status_code == 400


def test_missing_type_400():
    body = {k: v for k, v in _FULL_PAYLOAD.items() if k != "type"}
    body["id"] = "V-MISSING-TYPE-1"
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=body,
        )
    assert r.status_code == 400
    assert _get_violation("V-MISSING-TYPE-1") is None


def test_missing_captured_at_utc_400():
    body = {k: v for k, v in _FULL_PAYLOAD.items() if k != "capturedAtUtc"}
    body["id"] = "V-MISSING-CAPTURED-1"
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=body,
        )
    assert r.status_code == 400
    assert _get_violation("V-MISSING-CAPTURED-1") is None


def test_empty_id_400():
    body = {**_FULL_PAYLOAD, "id": "   "}
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=body,
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Ingested violation flows into the EXISTING citation bridge unchanged: a
# decision writes a decision_outbox row whose payload carries the ingested
# violation's real fields (uid in, uid out via violationId).
# ---------------------------------------------------------------------------
def test_decision_on_ingested_violation_flows_into_outbox_with_real_fields():
    ingest_body = {**_FULL_PAYLOAD, "id": "V-BRIDGE-260707-9999999"}
    with _with_secret(_SECRET):
        r = client.post(
            "/violations/from-rack",
            headers={"X-Rack-Secret": _SECRET},
            json=ingest_body,
        )
    assert r.status_code == 200, r.text

    sup = _auth("supervisor")
    patch = client.patch(
        "/violations/V-BRIDGE-260707-9999999/review",
        headers=sup,
        json={"status": "approved", "notes": "confirmed from rack footage"},
    )
    assert patch.status_code == 200, patch.text

    db = SessionLocal()
    try:
        rows = (
            db.query(models.DecisionOutbox)
            .filter(models.DecisionOutbox.violation_id == "V-BRIDGE-260707-9999999")
            .order_by(models.DecisionOutbox.id.asc())
            .all()
        )
    finally:
        db.close()

    assert len(rows) == 1
    row = rows[0]
    assert row.decision == "approved"
    p = row.payload
    # uid in, uid out via violationId — the SAME id the rack minted.
    assert p["violationId"] == "V-BRIDGE-260707-9999999"
    assert p["decision"] == "approved"
    assert p["reviewNotes"] == "confirmed from rack footage"

    v = p["violation"]
    assert v["plate"] == "SV-9911"
    assert v["type"] == "Speeding"
    assert v["speedMph"] == 62
    assert v["speedLimitMph"] == 40
    assert v["camera"] == "CAM-AV-07"
    assert v["location"] == {
        "lat": 13.1339,
        "lng": -61.2108,
        "label": "Leeward Hwy, Arnos Vale",
    }
    assert v["citable"] is True
    assert v["gateReason"] == "gate: citation class, certified basis"
    kinds = {e["kind"] for e in v["evidence"]}
    assert kinds == {"clip", "raw_clip", "screenshot"}
