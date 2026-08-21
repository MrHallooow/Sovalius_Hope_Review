"""TestClient coverage for the cameras + evidence routers.

Mirrors test_review_gateway.py's isolated temp SQLite + secret bootstrap (env
set BEFORE importing the app, since config loads at first import). NOTE: pytest
imports test modules alphabetically, so when the whole suite runs THIS module's
env wins and every module shares this tmpdir DB — assertions here are therefore
DB-state tolerant (no absolute row counts; audit rows are matched by
action/officer/detail, never by position).
"""

from __future__ import annotations

import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="revgw_camev_test_")
os.environ["GWREV_DB_URL"] = f"sqlite:///{pathlib.Path(_TMP, 't.db').as_posix()}"
os.environ["GWREV_JWT_SECRET"] = str(pathlib.Path(_TMP, "secret.bin"))
os.environ["GWREV_EVIDENCE_DIR"] = str(pathlib.Path(_TMP, "ev"))
os.environ["GWREV_SEED"] = "1"
os.environ["GWREV_SEED_PASSWORD"] = "review1234"

from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402

app = create_app()
client = TestClient(app)

_PW = "review1234"


def _login(username: str) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": _PW})
    assert r.status_code == 200, r.text
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _camera_change_rows(**detail_match) -> list:
    """All camera_change audit rows whose detail contains detail_match.
    Matched in Python (portable across SQLite/PG JSON) and by content, never
    by count/position — other modules share this DB when the suite runs."""
    from gateway import models
    from gateway.db import SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.action == "camera_change")
            .order_by(models.AuditLog.seq.asc())
            .all()
        )
        return [
            r
            for r in rows
            if all((r.detail or {}).get(k) == v for k, v in detail_match.items())
        ]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /cameras
# ---------------------------------------------------------------------------
def test_cameras_and_evidence_require_auth():
    assert client.get("/cameras").status_code == 401
    assert client.get("/cameras/CAM-AV-07/lanes").status_code == 401
    assert client.get("/violations/VIO-EVD-A/evidence").status_code == 401
    j = client.get("/cameras").json()
    assert j["code"] == "unauthorized"  # app error-mapping shape


def test_cameras_list_shape():
    a = _login("officer")  # plain bearer auth, no privilege needed to read
    r = client.get("/cameras", headers=_h(a["accessToken"]))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 7  # seed
    by_id = {c["id"]: c for c in items}
    assert "CAM-AV-07" in by_id
    cam = by_id["CAM-AV-07"]
    assert set(cam) == {"id", "location", "status", "lastPing"}
    assert cam["location"] and cam["status"]


# ---------------------------------------------------------------------------
# PATCH /cameras/{id} — canManageCameras + audit
# ---------------------------------------------------------------------------
def test_camera_patch_denied_without_privilege():
    o = _login("officer")  # seeded canManageCameras=False
    r = client.patch(
        "/cameras/CAM-KT-12",
        json={"status": "offline"},
        headers=_h(o["accessToken"]),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    # And the camera was NOT changed.
    a = _login("admin")
    cams = client.get("/cameras", headers=_h(a["accessToken"])).json()["items"]
    assert next(c for c in cams if c["id"] == "CAM-KT-12")["status"] == "online"


def test_camera_patch_updates_and_audits():
    from gateway import audit
    from gateway.db import SessionLocal

    a = _login("admin")
    r = client.patch(
        "/cameras/CAM-KT-15",
        json={"status": "maintenance", "location": "Kingstown Bypass (North)"},
        headers=_h(a["accessToken"]),
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["camera"]["status"] == "maintenance"
    assert j["camera"]["location"] == "Kingstown Bypass (North)"

    # Persisted (fresh read), not just echoed.
    cams = client.get("/cameras", headers=_h(a["accessToken"])).json()["items"]
    assert next(c for c in cams if c["id"] == "CAM-KT-15")["status"] == "maintenance"

    # Server-side tamper-evident audit row: WHO (from the token, never the
    # body) + WHAT (from/to per field), auditRef carries the AUD-CAM code.
    rows = _camera_change_rows(cameraId="CAM-KT-15")
    assert rows, "expected a camera_change audit row"
    row = rows[-1]
    assert row.officer == "admin"
    assert row.id.startswith("AUD-CAM")
    changes = row.detail["changes"]
    assert changes["status"]["to"] == "maintenance"
    assert changes["status"]["from"] == "degraded"  # seed value
    assert changes["location"]["to"] == "Kingstown Bypass (North)"

    # The chain still verifies after the mutation was appended.
    db = SessionLocal()
    try:
        assert audit.verify_chain(db)["ok"] is True
    finally:
        db.close()


def test_camera_patch_unknown_and_empty():
    a = _login("admin")
    h = _h(a["accessToken"])
    r = client.patch("/cameras/CAM-NOPE-99", json={"status": "x"}, headers=h)
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"
    # Legacy parity: no allowlisted field in the body -> 400 (unknown keys are
    # tolerated by the permissive schema but never written).
    r2 = client.patch("/cameras/CAM-KT-12", json={"nonsense": 1}, headers=h)
    assert r2.status_code == 400


# ---------------------------------------------------------------------------
# Camera lanes: GET null-parity, PUT UPSERT round-trip, privilege, audit
# ---------------------------------------------------------------------------
def test_lanes_absent_returns_null_data():
    a = _login("officer")
    r = client.get("/cameras/CAM-NO-LANES-YET/lanes", headers=_h(a["accessToken"]))
    assert r.status_code == 200  # main.js parity: data:null, NOT 404
    assert r.json() == {"ok": True, "data": None}


def test_lanes_put_denied_without_privilege():
    o = _login("officer")
    r = client.put(
        "/cameras/CAM-AV-07/lanes",
        json={"laneData": {"lanes": []}, "calibrationWidth": 1, "calibrationHeight": 1},
        headers=_h(o["accessToken"]),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_lanes_roundtrip_upsert_and_audit():
    s = _login("supervisor")  # seeded canManageCameras=True (not only admin)
    h = _h(s["accessToken"])
    lanes_v1 = {"lanes": [{"id": 1, "label": "SB-1", "points": [[10, 20], [30, 40]]}]}

    # CREATE (insert arm of the UPSERT).
    r1 = client.put(
        "/cameras/CAM-TEST-77/lanes",
        json={"laneData": lanes_v1, "calibrationWidth": 1280, "calibrationHeight": 720},
        headers=h,
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["laneData"] == lanes_v1
    assert d1["calibrationWidth"] == 1280 and d1["calibrationHeight"] == 720
    assert d1["updatedAt"]

    # Round-trip: a fresh GET returns exactly what was PUT.
    g1 = client.get("/cameras/CAM-TEST-77/lanes", headers=h)
    assert g1.status_code == 200
    gd1 = g1.json()["data"]
    assert gd1["laneData"] == lanes_v1
    assert gd1["calibrationWidth"] == 1280 and gd1["calibrationHeight"] == 720
    assert gd1["backgroundFrameUrl"] is None  # never client-writable via PUT
    assert gd1["backgroundFramePresigned"] is None

    # UPDATE (conflict arm): data is REPLACED, not merged.
    lanes_v2 = {
        "lanes": [
            {"id": 1, "label": "SB-1", "points": [[11, 21], [31, 41]]},
            {"id": 2, "label": "SB-2", "points": [[50, 60], [70, 80]]},
        ]
    }
    r2 = client.put(
        "/cameras/CAM-TEST-77/lanes",
        json={"laneData": lanes_v2, "calibrationWidth": 1920, "calibrationHeight": 1080},
        headers=h,
    )
    assert r2.status_code == 200
    gd2 = client.get("/cameras/CAM-TEST-77/lanes", headers=h).json()["data"]
    assert gd2["laneData"] == lanes_v2
    assert gd2["calibrationWidth"] == 1920 and gd2["calibrationHeight"] == 1080

    # Both mutations were audited (create then update), officer from the token.
    rows = _camera_change_rows(cameraName="CAM-TEST-77", op="lanes_upsert")
    assert [r.detail["created"] for r in rows] == [True, False]
    assert [r.detail["laneCount"] for r in rows] == [1, 2]
    assert all(r.officer == "supervisor" for r in rows)
    assert all(r.id.startswith("AUD-CAM") for r in rows)


def test_lanes_background_frame_presigned_fetchable():
    """When background_frame_url is set, GET lanes carries a presigned GET from
    the active store — in dev a SIGNED local token URL served by
    /evidence/blob/{token}, fetchable with NO bearer auth (the token IS the
    capability, like a real S3 presign)."""
    from gateway import models
    from gateway.db import SessionLocal

    key = "frames/CAM-AV-07/bg.jpg"
    payload = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    app.state.evidence_store.open_for_write(key, payload)

    stored_url = f"https://hope-evidence.s3.us-east-1.amazonaws.com/{key}"
    db = SessionLocal()
    try:
        row = db.get(models.CameraLane, "CAM-AV-07")
        assert row is not None, "seeded CAM-AV-07 lane row expected"
        row.background_frame_url = stored_url
        row.background_frame_at = models._utcnow()
        db.commit()
    finally:
        db.close()

    a = _login("officer")
    r = client.get("/cameras/CAM-AV-07/lanes", headers=_h(a["accessToken"]))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["backgroundFrameUrl"] == stored_url
    presigned = data["backgroundFramePresigned"]
    assert presigned and presigned.startswith("/evidence/blob/")
    assert key not in presigned  # capability is the signature, never the raw key

    blob = client.get(presigned)  # deliberately NO Authorization header
    assert blob.status_code == 200
    assert blob.content == payload
    assert blob.headers["content-type"] == "image/jpeg"


# ---------------------------------------------------------------------------
# GET /violations/{id}/evidence — case-bound presign + key-extraction parity
# ---------------------------------------------------------------------------
def _mk_violation(vid: str, **cols):
    """Insert a violation carrying the evidence pointers under test."""
    from datetime import datetime, timezone

    from gateway import models
    from gateway.db import SessionLocal

    db = SessionLocal()
    try:
        if db.get(models.Violation, vid) is None:
            db.add(
                models.Violation(
                    id=vid,
                    type="Speeding",
                    date=datetime(2026, 3, 1, tzinfo=timezone.utc),
                    **cols,
                )
            )
            db.commit()
    finally:
        db.close()


def _evidence_rows(violation_id: str) -> list:
    """evidence_accessed audit rows for one case (content-matched, not counted)."""
    from gateway import models
    from gateway.db import SessionLocal

    db = SessionLocal()
    try:
        return (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "evidence_accessed",
                models.AuditLog.violation_id == violation_id,
            )
            .order_by(models.AuditLog.seq.asc())
            .all()
        )
    finally:
        db.close()


def test_evidence_presign_and_fetch():
    key = "violations/VIO-EVD-A/clip.mp4"
    payload = b"mp4-clip-bytes"
    app.state.evidence_store.open_for_write(key, payload)
    _mk_violation(
        "VIO-EVD-A",
        # absolute URL -> pathname minus leading slash (main.js parity)
        clip_url=f"https://hope-evidence.s3.us-east-1.amazonaws.com/{key}",
        # bare key -> itself (documented divergence for local dev rows)
        screenshot_url="violations/VIO-EVD-A/shot.jpg",
        raw_clip_url="",  # no raw clip -> rawUrl AND tracksUrl null
    )

    a = _login("officer")
    r = client.get("/violations/VIO-EVD-A/evidence", headers=_h(a["accessToken"]))
    assert r.status_code == 200, r.text
    j = r.json()
    # main.js response names EXACTLY: raw clip comes back as rawUrl. Plus the
    # derived tracks.json sidecar URL (Phase 3 CPU-erasure, review side).
    assert set(j) == {"ok", "clipUrl", "rawUrl", "screenshotUrl", "tracksUrl"}
    assert j["ok"] is True
    assert j["rawUrl"] is None
    assert j["tracksUrl"] is None  # no raw clip -> nothing to derive from

    # The clip presign is fetchable via TestClient (no bearer auth needed).
    assert j["clipUrl"].startswith("/evidence/blob/")
    got = client.get(j["clipUrl"])
    assert got.status_code == 200
    assert got.content == payload
    assert got.headers["content-type"] == "video/mp4"

    # Presign does NOT check existence (S3 semantics + main.js parity): the
    # screenshot URL mints fine but 404s on fetch — never an issuance error.
    assert j["screenshotUrl"].startswith("/evidence/blob/")
    assert client.get(j["screenshotUrl"]).status_code == 404

    # Every issuance is attributable: who, which case, which capabilities —
    # and never the signed URLs themselves (they are bearer secrets).
    rows = _evidence_rows("VIO-EVD-A")
    assert rows, "evidence access must be audited"
    last = rows[-1]
    assert last.officer == "officer"
    assert last.detail["issued"] == ["clipUrl", "screenshotUrl"]
    assert "/evidence/blob/" not in str(last.detail)


def test_evidence_unknown_and_missing_yield_nulls():
    _mk_violation(
        "VIO-EVD-B",
        clip_url="/rooted/path.mp4",  # new URL("/x") throws in JS -> null
        screenshot_url="",  # empty -> null
        raw_clip_url="https://host.example/",  # no path -> null
    )
    a = _login("officer")
    r = client.get("/violations/VIO-EVD-B/evidence", headers=_h(a["accessToken"]))
    assert r.status_code == 200
    assert r.json() == {
        "ok": True,
        "clipUrl": None,
        "rawUrl": None,
        "screenshotUrl": None,
        "tracksUrl": None,
    }


def test_evidence_for_unknown_violation_is_404():
    """A key can no longer be smuggled in: evidence exists only for a case."""
    a = _login("officer")
    r = client.get("/violations/VIO-DOES-NOT-EXIST/evidence", headers=_h(a["accessToken"]))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# tracks.json sidecar derivation (Phase 3 CPU-erasure)
# ---------------------------------------------------------------------------
def test_evidence_derives_tracks_sidecar_from_raw_clip():
    """tracks.json lives NEXT TO clip_raw.mp4 in the same storage folder —
    the key is derived, never stored, and presigned through the identical
    store/token mechanism as the clips themselves."""
    raw_key = "violations/VIO-EVD-C/clip_raw.mp4"
    tracks_key = "violations/VIO-EVD-C/tracks.json"
    payload = b'{"version":1,"frames":[]}'
    app.state.evidence_store.open_for_write(tracks_key, payload)
    _mk_violation(
        "VIO-EVD-C",
        raw_clip_url=f"https://hope-evidence.s3.us-east-1.amazonaws.com/{raw_key}",
    )

    a = _login("officer")
    r = client.get("/violations/VIO-EVD-C/evidence", headers=_h(a["accessToken"]))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["tracksUrl"] is not None
    assert j["tracksUrl"].startswith("/evidence/blob/")
    assert tracks_key not in j["tracksUrl"]  # capability is the signature, never the raw key

    got = client.get(j["tracksUrl"])  # no bearer auth needed — same as other evidence blobs
    assert got.status_code == 200
    assert got.content == payload
    assert got.headers["content-type"] == "application/json"


def test_evidence_tracks_sidecar_mints_but_404s_when_never_uploaded():
    """Old evidence (no tracks.json ever produced) must degrade gracefully:
    a mintable-but-404ing tracksUrl, never an issuance error."""
    _mk_violation(
        "VIO-EVD-D",
        raw_clip_url="violations/VIO-EVD-D/clip_raw.mp4",  # bare key, never uploaded
    )
    a = _login("officer")
    r = client.get("/violations/VIO-EVD-D/evidence", headers=_h(a["accessToken"]))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["tracksUrl"].startswith("/evidence/blob/")
    assert client.get(j["tracksUrl"]).status_code == 404


def test_sibling_key_derivation():
    from gateway.routers.evidence import sibling_key

    assert sibling_key("violations/VIO-1/clip_raw.mp4", "tracks.json") == "violations/VIO-1/tracks.json"
    assert sibling_key("clip_raw.mp4", "tracks.json") == "tracks.json"  # no folder
    assert sibling_key(None, "tracks.json") is None
    assert sibling_key("", "tracks.json") is None


def test_extract_key_main_js_parity():
    from gateway.routers.evidence import extract_key

    assert extract_key(None) is None
    assert extract_key("") is None
    assert extract_key("   ") is None
    assert (
        extract_key("https://b.s3.us-east-1.amazonaws.com/violations/V-1/clip.mp4")
        == "violations/V-1/clip.mp4"
    )
    assert extract_key("s3://bucket/violations/V-1/clip.mp4") == "violations/V-1/clip.mp4"
    # Percent-encoding preserved exactly like JS new URL().pathname.
    assert extract_key("https://h/a%20b/c.mp4") == "a%20b/c.mp4"
    # Bare key -> itself (documented divergence from main.js).
    assert extract_key("violations/V-1/clip.mp4") == "violations/V-1/clip.mp4"
    # Rooted path (new URL throws without a base) and bare-host -> None.
    assert extract_key("/violations/V-1/clip.mp4") is None
    assert extract_key("https://host.example") is None


# ---------------------------------------------------------------------------
# /evidence/blob/{token} — the local presign capability boundary
# ---------------------------------------------------------------------------
def test_blob_route_rejects_bad_tokens_uniformly():
    from gateway.storage import mint_blob_token

    key = "violations/VIO-EVD-A/clip.mp4"  # exists (uploaded above)

    # Garbage token.
    assert client.get("/evidence/blob/not-a-token").status_code == 404
    # Expired token for a REAL object.
    expired = mint_blob_token(key, ttl_sec=-5)
    assert client.get(f"/evidence/blob/{expired}").status_code == 404
    # Tampered signature on an otherwise-valid token.
    good = mint_blob_token(key, ttl_sec=60)
    p64, sig = good.rsplit(".", 1)
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert client.get(f"/evidence/blob/{p64}.{flipped}").status_code == 404
    # Valid signature but the object was never uploaded.
    ghost = mint_blob_token("violations/VIO-0000-99999/none.bin", ttl_sec=60)
    assert client.get(f"/evidence/blob/{ghost}").status_code == 404
    # All indistinguishable to a prober: same status, same error shape.
    body = client.get(f"/evidence/blob/{expired}").json()
    assert body["code"] == "not_found"
    # And the untampered token still works — the flip test didn't break it.
    ok = client.get(f"/evidence/blob/{good}")
    assert ok.status_code == 200 and ok.content == b"mp4-clip-bytes"


# ---------------------------------------------------------------------------
# GET /camera-lanes — the all-lanes listing behind db:get-all-camera-lanes
# ---------------------------------------------------------------------------
def test_all_camera_lanes_requires_auth():
    r = client.get("/camera-lanes")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_all_camera_lanes_legacy_row_shape_and_order():
    """Rows carry the LEGACY snake_case IPC column names (the renderer's
    LaneConfigTab reads r.camera_name verbatim) ordered by camera_name; plain
    bearer auth suffices (reading calibration needs no privilege)."""
    a = _login("officer")
    r = client.get("/camera-lanes", headers=_h(a["accessToken"]))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    rows = j["rows"]
    names = [x["camera_name"] for x in rows]
    assert "CAM-AV-07" in names  # seed
    assert names == sorted(names)
    row = next(x for x in rows if x["camera_name"] == "CAM-AV-07")
    assert set(row) == {
        "camera_name",
        "lane_data",
        "calibration_width",
        "calibration_height",
        "updated_at",
    }
    assert isinstance(row["lane_data"], (dict, list))
    assert row["calibration_width"] == 1920 and row["calibration_height"] == 1080
