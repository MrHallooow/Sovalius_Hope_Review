"""TestClient coverage for the review gateway core. Uses an isolated temp
SQLite DB + secret (env vars set BEFORE importing the app, since config loads
at first import). Per-test settings tweaks use dataclasses.replace on the
importing module's settings object — env vars set inside tests are IGNORED."""

from __future__ import annotations

import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="revgw_test_")
os.environ["GWREV_DB_URL"] = f"sqlite:///{pathlib.Path(_TMP, 't.db').as_posix()}"
os.environ["GWREV_JWT_SECRET"] = str(pathlib.Path(_TMP, "secret.bin"))
os.environ["GWREV_EVIDENCE_DIR"] = str(pathlib.Path(_TMP, "ev"))
os.environ["GWREV_SEED"] = "1"
os.environ["GWREV_SEED_PASSWORD"] = "review1234"

from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402

client = TestClient(create_app())

_PW = "review1234"


def _login(username: str = "officer", password: str = _PW) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Liveness / readiness / error shape
# ---------------------------------------------------------------------------
def test_health():
    j = client.get("/health").json()
    assert j["status"] == "ok"
    assert j["service"] == "review-gateway"


def test_ready_ok():
    r = client.get("/ready")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ready"
    assert j["checks"] == {"db": "ok", "storage": "ok"}


def test_request_id_header():
    r = client.get("/health")
    assert r.headers.get("x-request-id")
    echoed = client.get("/health", headers={"X-Request-Id": "req-fixed-1"})
    assert echoed.headers["x-request-id"] == "req-fixed-1"


def test_error_shape_top_level():
    # Unknown path -> the app's {code,message,retryable} error contract.
    r = client.get("/definitely-not-a-route")
    assert r.status_code == 404
    j = r.json()
    assert j["code"] == "not_found"
    assert set(j) == {"code", "message", "retryable"}


# ---------------------------------------------------------------------------
# Login: shape, bad credentials, throttle/lockout
# ---------------------------------------------------------------------------
def test_login_shape():
    a = _login("admin")
    assert a["ok"] is True
    assert a["accessToken"] and a["refreshToken"]
    u = a["user"]
    assert u["username"] == "admin"
    assert u["role"] == "admin"
    assert u["privileges"]["canManageUsers"] is True
    assert u["name"]  # display_name mapped to "name" per the IPC contract
    assert "theme" in u and "preferences" in u and "keybinds" in u


def test_login_username_normalised():
    # main.js lower-cased + trimmed usernames; the gateway must match.
    a = _login("  OFFICER  ")
    assert a["user"]["username"] == "officer"


def test_login_bad_password():
    r = client.post(
        "/auth/login", json={"username": "officer", "password": "wrong"}
    )
    assert r.status_code == 401
    j = r.json()
    assert j["code"] == "unauthorized"  # shape the app's error mapping reads
    assert "retryable" in j


def test_login_unknown_user_same_shape():
    r = client.post(
        "/auth/login", json={"username": "no-such-user", "password": "whatever"}
    )
    assert r.status_code == 401
    # Same generic body as a bad password — no username enumeration.
    assert r.json()["message"] == "Invalid username or password"


def _throttled_client(max_failures: int = 3) -> TestClient:
    """A TestClient on a fresh app whose login throttle is replaced with a
    low-threshold, isolated instance (so its per-IP lockout doesn't bleed into
    the module-level `client` shared by every other test)."""
    from gateway.app import create_app
    from gateway.ratelimit import LoginThrottle

    app = create_app()
    app.state.login_throttle = LoginThrottle(
        max_failures=max_failures, window_sec=60, lockout_sec=300, user_lockout_sec=300
    )
    return TestClient(app)


def test_login_lockout():
    c = _throttled_client(max_failures=3)
    body = {"username": "officer"}
    for _ in range(3):
        r = c.post("/auth/login", json={**body, "password": "wrong"})
        assert r.status_code == 401
        assert r.json()["code"] == "unauthorized"
    # 4th attempt is locked out — top-level rate_limited + Retry-After header.
    locked = c.post("/auth/login", json={**body, "password": "wrong"})
    assert locked.status_code == 429
    j = locked.json()
    assert j["code"] == "rate_limited" and j["retryable"] is True
    assert int(locked.headers["retry-after"]) > 0
    # Even the CORRECT password is refused while locked.
    still = c.post("/auth/login", json={**body, "password": _PW})
    assert still.status_code == 429


def test_login_success_clears_user():
    c = _throttled_client(max_failures=3)
    body = {"username": "officer"}
    assert c.post("/auth/login", json={**body, "password": "wrong"}).status_code == 401
    assert c.post("/auth/login", json={**body, "password": "wrong"}).status_code == 401
    # Success clears the username window before the 3rd failure trips lockout.
    assert c.post("/auth/login", json={**body, "password": _PW}).status_code == 200
    # A subsequent bad attempt does NOT immediately 429 (window was cleared).
    assert c.post("/auth/login", json={**body, "password": "wrong"}).status_code == 401


# ---------------------------------------------------------------------------
# Refresh rotation + family reuse-detection (lifted, proven mechanism)
# ---------------------------------------------------------------------------
def test_refresh_rotation():
    a = _login("officer")
    old = a["refreshToken"]
    r1 = client.post("/auth/refresh", json={"refreshToken": old})
    assert r1.status_code == 200
    new = r1.json()["refreshToken"]
    assert new and new != old  # token is rotated, not echoed
    # New token works once and itself rotates to a different token. (We rotate
    # the live leaf BEFORE re-presenting `old` — re-presenting a rotated-out
    # token is a compromise signal and revokes the whole family; covered by
    # test_refresh_reuse_detection.)
    r2 = client.post("/auth/refresh", json={"refreshToken": new})
    assert r2.status_code == 200
    assert r2.json()["refreshToken"] != new
    # The rotated-out `new` is now rejected.
    assert client.post("/auth/refresh", json={"refreshToken": new}).status_code == 401


def test_refresh_reuse_detection():
    from gateway import models
    from gateway.db import SessionLocal

    a = _login("officer")
    t0 = a["refreshToken"]
    r = client.post("/auth/refresh", json={"refreshToken": t0})
    t1 = r.json()["refreshToken"]
    # Re-present the already-rotated T0 -> reuse detected -> 401.
    reuse = client.post("/auth/refresh", json={"refreshToken": t0})
    assert reuse.status_code == 401
    # The whole family is now revoked: T1 (the live leaf) is also rejected.
    assert client.post("/auth/refresh", json={"refreshToken": t1}).status_code == 401
    # reused_at was stamped on the re-presented row.
    db = SessionLocal()
    try:
        row = db.get(models.RefreshToken, t0)
        assert row is not None and row.reused_at is not None
    finally:
        db.close()


def test_logout_revokes_family():
    a = _login("officer")
    ancestor = a["refreshToken"]
    leaf = client.post("/auth/refresh", json={"refreshToken": ancestor}).json()[
        "refreshToken"
    ]
    assert client.post("/auth/logout", json={"refreshToken": leaf}).status_code == 204
    assert client.post("/auth/refresh", json={"refreshToken": leaf}).status_code == 401
    assert (
        client.post("/auth/refresh", json={"refreshToken": ancestor}).status_code == 401
    )


def test_logout_all():
    a1 = _login("officer")
    a2 = _login("officer")
    r = client.post("/auth/logout-all", headers=_h(a1["accessToken"]))
    assert r.status_code == 204
    assert (
        client.post("/auth/refresh", json={"refreshToken": a1["refreshToken"]}).status_code
        == 401
    )
    assert (
        client.post("/auth/refresh", json={"refreshToken": a2["refreshToken"]}).status_code
        == 401
    )


def test_refresh_token_rejected_as_access_token():
    a = _login("supervisor")
    # A refresh token presented as a bearer access token must be refused.
    r = client.get("/audit/verify", headers=_h(a["refreshToken"]))
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Live-row authorization: privilege revocation + soft-delete are IMMEDIATE
# ---------------------------------------------------------------------------
def test_privilege_endpoint_forbidden_for_officer():
    # Seeded officer has canViewAudit=False -> 403 with the app error shape.
    a = _login("officer")
    r = client.get("/audit/log", headers=_h(a["accessToken"]))
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_require_privilege_live_revocation():
    from gateway import models
    from gateway.db import SessionLocal

    a = _login("supervisor")
    h = _h(a["accessToken"])
    ok = client.get("/audit/log", headers=h)
    assert ok.status_code == 200, ok.text
    assert isinstance(ok.json()["items"], list)

    db = SessionLocal()
    try:
        u = db.query(models.User).filter(models.User.username == "supervisor").one()
        orig = dict(u.privileges or {})
        # Revoke the privilege — the SAME still-valid access token must now 403
        # (authz reads the live row, not the JWT claims).
        u.privileges = {**orig, "canViewAudit": False}
        db.commit()
        denied = client.get("/audit/log", headers=h)
        assert denied.status_code == 403
        assert denied.json()["code"] == "forbidden"
        # Restore -> immediately allowed again.
        u.privileges = orig
        db.commit()
        again = client.get("/audit/log", headers=h)
        assert again.status_code == 200
    finally:
        db.close()


def test_inactive_user_rejected_with_valid_token():
    from gateway import models
    from gateway.db import SessionLocal

    a = _login("officer")
    h = _h(a["accessToken"])
    db = SessionLocal()
    try:
        u = db.query(models.User).filter(models.User.username == "officer").one()
        u.active = False
        db.commit()
        # Soft-delete takes effect immediately, even with a valid access token.
        r = client.post("/auth/logout-all", headers=h)
        assert r.status_code == 401
        # And refresh (a credential surface) is refused too.
        rr = client.post("/auth/refresh", json={"refreshToken": a["refreshToken"]})
        assert rr.status_code == 401
        u.active = True
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Audit immutability: hash chain, verify, tamper detection, append-only guard,
# RBAC endpoint, CLI.
# ---------------------------------------------------------------------------
def test_audit_chain_grows():
    from gateway import models
    from gateway.audit import GENESIS
    from gateway.db import SessionLocal

    # Logins are audited server-side (AUD-LOG), so generate at least two rows.
    _login("officer")
    _login("supervisor")

    db = SessionLocal()
    try:
        rows = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).all()
        assert len(rows) >= 2
        assert any(r.action == "login" for r in rows)
        # Contiguous 1..N, genesis on row 1, each prev_hash == prior row_hash.
        assert [r.seq for r in rows] == list(range(1, len(rows) + 1))
        assert rows[0].prev_hash == GENESIS
        for i in range(1, len(rows)):
            assert rows[i].prev_hash == rows[i - 1].row_hash
        # row_hash is populated (non-empty hex) and auditRefs carry the code.
        assert all(len(r.row_hash) == 64 for r in rows)
        assert any(r.id.startswith("AUD-LOG") for r in rows)
    finally:
        db.close()


def test_audit_verify_ok():
    from gateway import audit, models
    from gateway.db import SessionLocal

    db = SessionLocal()
    try:
        n = db.query(models.AuditLog).count()
        r = audit.verify_chain(db)
    finally:
        db.close()
    assert r["ok"] is True
    assert r["checked"] == n
    assert r["first_broken_seq"] is None


def test_audit_record_stages_but_does_not_commit():
    from gateway import audit, models
    from gateway.db import SessionLocal

    db = SessionLocal()
    try:
        before = db.query(models.AuditLog).count()
        audit.record(db, officer="system", action="violation_viewed",
                     violation_id="VIO-2026-00147")
        # Staged in THIS session, but a parallel session must not see it yet.
        other = SessionLocal()
        try:
            assert other.query(models.AuditLog).count() == before
        finally:
            other.close()
        db.rollback()  # discard — proves record() itself never committed
        assert db.query(models.AuditLog).count() == before
    finally:
        db.close()


def test_audit_detects_mutation():
    # Tamper inside a transaction we roll back, so the shared `client` DB stays
    # intact for later tests. Raw SQL UPDATE bypasses the ORM append-only guard
    # (simulating a DBA / attacker with table access) — the hash chain still
    # catches it.
    from sqlalchemy import text

    from gateway import audit, models
    from gateway.db import SessionLocal

    _login("officer")  # ensure >=1 audit row exists

    db = SessionLocal()
    try:
        first = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).first()
        assert first is not None
        seq = first.seq
        db.execute(
            text("UPDATE audit_log SET notes='tampered' WHERE seq=:s"), {"s": seq}
        )
        db.expire_all()  # drop the identity-map cache so verify reads fresh rows
        r = audit.verify_chain(db)
        assert r["ok"] is False
        assert r["first_broken_seq"] == seq
        assert "hash" in r["reason"].lower()
    finally:
        db.rollback()  # undo the tamper — shared DB restored
        db.close()


def test_audit_detects_deletion():
    # Delete a middle row inside a rolled-back transaction -> contiguity gap.
    from sqlalchemy import text

    from gateway import audit, models
    from gateway.db import SessionLocal

    for _ in range(3):  # ensure >=3 rows so a middle one exists
        _login("officer")

    db = SessionLocal()
    try:
        rows = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).all()
        assert len(rows) >= 3, "need >=3 rows to delete a middle one"
        victim = rows[1].seq
        db.execute(text("DELETE FROM audit_log WHERE seq=:s"), {"s": victim})
        db.expire_all()
        r = audit.verify_chain(db)
        assert r["ok"] is False
        # The gap is detected at the row AFTER the deleted one (seq jumps).
        assert r["first_broken_seq"] == victim + 1
        assert "gap" in r["reason"].lower() or "deleted" in r["reason"].lower()
    finally:
        db.rollback()
        db.close()


def test_append_only_guard():
    import pytest

    from gateway import models
    from gateway.db import SessionLocal

    # Self-sufficient: guarantee at least one audit row via the normal append
    # path (logins are audited server-side), so this test passes even when the
    # rest of the module is deselected (pytest -k append_only).
    _login("officer")

    db = SessionLocal()
    try:
        row = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).first()
        assert row is not None
        row.notes = "should-not-flush"
        with pytest.raises(RuntimeError, match="append-only"):
            db.flush()
        db.rollback()
        # DELETE via the ORM is refused too.
        row2 = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).first()
        db.delete(row2)
        with pytest.raises(RuntimeError, match="append-only"):
            db.flush()
        db.rollback()
    finally:
        db.close()


def test_verify_endpoint_rbac():
    # officer role is neither supervisor nor admin -> 403.
    a = _login("officer")
    r = client.get("/audit/verify", headers=_h(a["accessToken"]))
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"

    # supervisor -> 200 + integrity metadata only.
    s = _login("supervisor")
    hs = _h(s["accessToken"])
    ok = client.get("/audit/verify", headers=hs)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True
    # Metadata only — never bulk audit content.
    assert set(body) == {"ok", "checked", "headSeq", "headHash", "firstBrokenSeq", "reason"}

    head = client.get("/audit/head", headers=hs)
    assert head.status_code == 200
    assert set(head.json()) == {"seq", "hash", "count"}

    # No token at all -> 401.
    assert client.get("/audit/verify").status_code == 401


def test_cli_verify_exit_code():
    from gateway import cli_audit

    assert cli_audit.main(["verify"]) == 0
    assert cli_audit.main(["head"]) == 0


# ---------------------------------------------------------------------------
# JWT secret provisioning: env value precedence + prod no-autogen
# ---------------------------------------------------------------------------
def test_secret_value_env_and_prod_no_autogen():
    import base64
    import dataclasses

    import pytest

    import gateway.security as sec

    orig_settings = sec.settings
    orig_cache = sec._secret_cache
    raw = base64.b64encode(b"k" * 32).decode()
    # Point at a path that does NOT exist so we'd auto-generate if value missed.
    nonexist = orig_settings.jwt_secret_path.parent / "does_not_exist_secret.bin"
    if nonexist.exists():
        nonexist.unlink()
    try:
        # (1) GWREV_JWT_SECRET_VALUE wins and never writes a file.
        sec._secret_cache = None
        sec.settings = dataclasses.replace(
            orig_settings, jwt_secret_value=raw, jwt_secret_path=nonexist
        )
        assert sec._secret() == b"k" * 32
        assert not nonexist.exists()

        # (2) prod + neither value nor file -> RuntimeError (no silent autogen).
        sec._secret_cache = None
        sec.settings = dataclasses.replace(
            orig_settings, jwt_secret_value="", jwt_secret_path=nonexist, env="prod"
        )
        with pytest.raises(RuntimeError):
            sec._secret()
    finally:
        sec.settings = orig_settings
        sec._secret_cache = orig_cache


# ---------------------------------------------------------------------------
# Seed hygiene + storage factory
# ---------------------------------------------------------------------------
def test_seeded_users_exist_with_expected_privileges():
    from gateway import models
    from gateway.db import SessionLocal

    db = SessionLocal()
    try:
        users = {u.username: u for u in db.query(models.User).all()}
    finally:
        db.close()
    assert {"admin", "supervisor", "officer"} <= set(users)
    assert users["admin"].privileges["canManageUsers"] is True
    assert users["supervisor"].privileges["canManageUsers"] is False
    assert users["officer"].privileges["canViewAudit"] is False
    # Passwords are stored as bcrypt hashes, never plaintext.
    assert all(u.password_hash.startswith("$2") for u in users.values())


def test_seed_refuses_in_prod():
    import dataclasses

    import gateway.seed as seed_module
    from gateway import models
    from gateway.db import SessionLocal

    orig = seed_module.settings
    db = SessionLocal()
    try:
        # Delete nothing; just prove the guard returns before touching the DB.
        seed_module.settings = dataclasses.replace(orig, env="prod")
        before = db.query(models.User).count()
        seed_module.seed(db)
        assert db.query(models.User).count() == before
    finally:
        seed_module.settings = orig
        db.close()


def test_storage_factory_defaults_local_and_s3_is_lazy():
    import dataclasses

    from gateway.config import settings
    from gateway.storage import LocalDiskStore, S3Store, build_store

    assert isinstance(build_store(settings), LocalDiskStore)
    # The s3 seam selects S3Store WITHOUT importing boto3 (lazy client build).
    s3 = build_store(dataclasses.replace(settings, evidence_store="s3"))
    assert isinstance(s3, S3Store)
    assert s3._client is None  # no boto3 import, no network


def test_local_store_roundtrip_and_presign_get():
    import dataclasses
    import hashlib

    from gateway.config import settings
    from gateway.storage import LocalDiskStore, verify_blob_token

    store = LocalDiskStore(
        dataclasses.replace(settings, public_base_url="http://127.0.0.1:8090")
    )
    payload = b"clip-bytes"
    key = "violations/VIO-2026-00147/clip.mp4"
    assert store.open_for_write(key, payload) == len(payload)
    info = store.head(key)
    assert info is not None
    assert info.size == len(payload)
    assert info.sha256 == hashlib.sha256(payload).hexdigest()
    # Presign is a SIGNED, expiring token URL (review keys are guessable, so —
    # unlike the dispatch dev presign — the raw key must never be the
    # capability). The token round-trips back to the key it was minted for.
    url = store.presign_get(key)
    assert url.startswith("http://127.0.0.1:8090/evidence/blob/")
    token = url.rsplit("/", 1)[1]
    assert key not in url  # raw key never appears in the URL
    assert verify_blob_token(token) == key
    assert store.read(key) == payload
    store.delete(key)
    assert store.head(key) is None
    assert store.read(key) is None
