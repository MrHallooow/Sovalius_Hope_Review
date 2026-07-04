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
    assert client.get("/evidence/urls").status_code == 401
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
# GET /evidence/urls — main.js extractS3Key parity + presign fetch
# ---------------------------------------------------------------------------
def test_evidence_urls_presign_and_fetch():
    key = "violations/VIO-2026-00147/clip.mp4"
    payload = b"mp4-clip-bytes"
    app.state.evidence_store.open_for_write(key, payload)

    a = _login("officer")
    r = client.get(
        "/evidence/urls",
        params={
            # absolute URL -> pathname minus leading slash (main.js parity)
            "clipUrl": f"https://hope-evidence.s3.us-east-1.amazonaws.com/{key}",
            # bare key -> itself (documented divergence for local dev rows)
            "screenshotUrl": "violations/VIO-2026-00147/shot.jpg",
            # rawClipUrl omitted entirely -> rawUrl null
        },
        headers=_h(a["accessToken"]),
    )
    assert r.status_code == 200, r.text
    j = r.json()
    # main.js response names EXACTLY: raw clip comes back as rawUrl.
    assert set(j) == {"ok", "clipUrl", "rawUrl", "screenshotUrl"}
    assert j["ok"] is True
    assert j["rawUrl"] is None

    # The clip presign is fetchable via TestClient (no bearer auth needed).
    assert j["clipUrl"].startswith("/evidence/blob/")
    got = client.get(j["clipUrl"])
    assert got.status_code == 200
    assert got.content == payload
    assert got.headers["content-type"] == "video/mp4"

    # Presign does NOT check existence (S3 semantics + main.js parity): the
    # screenshot URL mints fine but 404s on fetch — never an /urls error.
    assert j["screenshotUrl"].startswith("/evidence/blob/")
    assert client.get(j["screenshotUrl"]).status_code == 404


def test_evidence_urls_unknown_and_missing_yield_nulls():
    a = _login("officer")
    r = client.get(
        "/evidence/urls",
        params={
            "clipUrl": "/rooted/path.mp4",  # new URL("/x") throws in JS -> null
            "screenshotUrl": "",  # empty -> null
            "rawClipUrl": "https://host.example/",  # no path -> null
        },
        headers=_h(a["accessToken"]),
    )
    assert r.status_code == 200
    assert r.json() == {
        "ok": True,
        "clipUrl": None,
        "rawUrl": None,
        "screenshotUrl": None,
    }


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

    key = "violations/VIO-2026-00147/clip.mp4"  # exists (uploaded above)

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
