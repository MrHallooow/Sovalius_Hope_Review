"""TestClient coverage for the users / prefs / system routers.

Covers the four task-mandated surfaces:
  * privilege matrix   — every user-admin + services mutation is refused for
                         the wrong role/privilege and allowed for the right one
                         (no implicit role bypass; live revocation via the API)
  * disabled-user token death — soft-delete (DELETE) and PATCH active=false
                         kill the existing access token at the dependency
                         check, refuse /auth/refresh, and refuse login with the
                         IDENTICAL generic 401 body as a wrong password
  * prefs isolation    — GET/PUT /prefs only ever touches the caller's own row
  * audit rows         — every user mutation writes exactly one server-side
                         user_admin row (register/update/password_change/
                         deactivate), officer taken from the token, never any
                         password material; chain still verifies afterwards

Isolated temp SQLite DB + secret set BEFORE importing any gateway module
(config loads at first import; whichever test file pytest collects first wins
the env race — all files set the same seed password so the shared DB works
either way). Per-test settings tweaks would use dataclasses.replace on the
importing module's settings object; env vars set inside tests are IGNORED.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="revgw_usp_test_")
os.environ["GWREV_DB_URL"] = f"sqlite:///{pathlib.Path(_TMP, 't.db').as_posix()}"
os.environ["GWREV_JWT_SECRET"] = str(pathlib.Path(_TMP, "secret.bin"))
os.environ["GWREV_EVIDENCE_DIR"] = str(pathlib.Path(_TMP, "ev"))
os.environ["GWREV_SEED"] = "1"
os.environ["GWREV_SEED_PASSWORD"] = "review1234"

from fastapi.testclient import TestClient  # noqa: E402

from gateway import models  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.db import SessionLocal  # noqa: E402
from gateway.ratelimit import LoginThrottle  # noqa: E402

app = create_app()
# The login throttle counts failures per client IP across ALL usernames and a
# success never clears the IP key — TestClient traffic is one IP, so the small
# number of deliberate bad-credential logins below would eventually 429 later
# tests. Throttle BEHAVIOUR is covered by test_review_gateway; here we swap in
# a high-threshold instance (app.state is test-injectable by design) so these
# tests assert authn/authz semantics, not rate limiting.
app.state.login_throttle = LoginThrottle(max_failures=10_000)
client = TestClient(app)

_PW = "review1234"


def _login(username: str, password: str = _PW) -> dict:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(
    admin_token: str,
    username: str,
    password: str = "pw-longenough-1",
    role: str = "officer",
    privileges: dict | None = None,
) -> dict:
    r = client.post(
        "/auth/register",
        headers=_h(admin_token),
        json={
            "username": username,
            "password": password,
            "displayName": username.strip().title(),  # legacy IPC arg name
            "role": role,
            "privileges": privileges or {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    return body["user"]


def _audit_rows(action: str) -> list:
    """All audit rows for one action code, chain order. Rows stay readable
    after close (attributes loaded eagerly; expire_on_commit=False)."""
    db = SessionLocal()
    try:
        return (
            db.query(models.AuditLog)
            .filter(models.AuditLog.action == action)
            .order_by(models.AuditLog.seq.asc())
            .all()
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Privilege matrix — user administration
# ---------------------------------------------------------------------------
def test_user_admin_privilege_matrix():
    admin = _login("admin")["accessToken"]
    officer = _login("officer")["accessToken"]
    supervisor = _login("supervisor")["accessToken"]

    reg_body = {"username": "matrix-reject", "password": "pw-longenough-1"}

    # Seeded officer AND supervisor both lack canManageUsers -> every
    # user-admin surface is 403 (role alone never grants anything).
    for tok in (officer, supervisor):
        h = _h(tok)
        assert client.post("/auth/register", headers=h, json=reg_body).status_code == 403
        assert client.get("/auth/users", headers=h).status_code == 403
        assert (
            client.patch("/auth/users/1", headers=h, json={"displayName": "X"}).status_code
            == 403
        )
        assert client.delete("/auth/users/1", headers=h).status_code == 403

    # No token at all is 401 (authn), not 403 (authz).
    assert client.get("/auth/users").status_code == 401
    assert client.post("/auth/register", json=reg_body).status_code == 401

    # admin ROLE without the canManageUsers PRIVILEGE: still refused — there
    # is no implicit role bypass on the privilege gates.
    _register(admin, "adminnopriv", role="admin", privileges={})
    anp = _login("adminnopriv", "pw-longenough-1")["accessToken"]
    assert client.post("/auth/register", headers=_h(anp), json=reg_body).status_code == 403
    assert client.get("/auth/users", headers=_h(anp)).status_code == 403

    # supervisor ROLE with canManageUsers: list + benign PATCH work, but
    # register stays admin-role-gated and role/privilege GRANTS are refused
    # (the privilege-escalation guard).
    mgr = _register(admin, "mgr1", role="supervisor", privileges={"canManageUsers": True})
    mt = _login("mgr1", "pw-longenough-1")["accessToken"]
    assert client.get("/auth/users", headers=_h(mt)).status_code == 200
    target = _register(admin, "matrix-target")
    ok = client.patch(
        f"/auth/users/{target['id']}", headers=_h(mt), json={"displayName": "Renamed By Mgr"}
    )
    assert ok.status_code == 200
    assert ok.json()["user"]["name"] == "Renamed By Mgr"
    # Self-promotion / privilege self-grant attempts -> 403.
    for payload in (
        {"role": "admin"},
        {"privileges": {"canManageUsers": True, "canViewAudit": True}},
    ):
        r = client.patch(f"/auth/users/{mgr['id']}", headers=_h(mt), json=payload)
        assert r.status_code == 403, payload
    assert client.post("/auth/register", headers=_h(mt), json=reg_body).status_code == 403

    # The rejected username was never created by any of the refused attempts.
    db = SessionLocal()
    try:
        assert (
            db.query(models.User)
            .filter(models.User.username == "matrix-reject")
            .one_or_none()
            is None
        )
    finally:
        db.close()

    # admin + canManageUsers passes; the listing never leaks credentials.
    listed = client.get("/auth/users", headers=_h(admin))
    assert listed.status_code == 200
    users = listed.json()["users"]
    assert {"admin", "supervisor", "officer"} <= {u["username"] for u in users}
    assert all("password" not in u and "password_hash" not in u for u in users)

    # LIVE REVOCATION via the API itself: admin strips mgr1's privilege ->
    # the SAME still-valid mgr token is refused on its very next request.
    r = client.patch(
        f"/auth/users/{mgr['id']}",
        headers=_h(admin),
        json={"privileges": {"canManageUsers": False}},
    )
    assert r.status_code == 200
    denied = client.get("/auth/users", headers=_h(mt))
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"


def test_register_validation_and_normalisation():
    admin = _login("admin")["accessToken"]
    h = _h(admin)
    # Short password / unknown role / blank username -> 400.
    assert (
        client.post(
            "/auth/register", headers=h, json={"username": "shorty", "password": "short"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/auth/register",
            headers=h,
            json={"username": "badrole", "password": "pw-longenough-1", "role": "root"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/auth/register", headers=h, json={"username": "   ", "password": "pw-longenough-1"}
        ).status_code
        == 400
    )

    # Username normalised (strip+lower) exactly like login; permissive extra
    # keys are tolerated but never read (active/id below change nothing).
    r = client.post(
        "/auth/register",
        headers=h,
        json={
            "username": "  MixedCase  ",
            "password": "mixed-pass-123",
            "id": 424242,
            "active": False,
        },
    )
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["username"] == "mixedcase"
    assert u["active"] is True  # client-supplied active was ignored
    assert u["id"] != 424242
    # bcrypt happened IN the gateway: the fresh credential logs in.
    assert _login("mixedcase", "mixed-pass-123")["ok"] is True
    # ...with default {} privileges: no user-admin access.
    t = _login("mixedcase", "mixed-pass-123")["accessToken"]
    assert client.get("/auth/users", headers=_h(t)).status_code == 403

    # Duplicate (case-insensitively) -> 409 conflict, top-level error shape.
    dup = client.post(
        "/auth/register",
        headers=h,
        json={"username": "MIXEDCASE", "password": "another-pass-1"},
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "conflict"


def test_patch_user_guards():
    admin_login = _login("admin")
    admin = admin_login["accessToken"]
    admin_id = admin_login["user"]["id"]
    h = _h(admin)
    target = _register(admin, "patchtarget", password="patchtarget-1pw")

    # password is NOT a PATCHable field: a body carrying ONLY password is
    # "no valid fields" (400) and the credential is untouched.
    r = client.patch(
        f"/auth/users/{target['id']}", headers=h, json={"password": "hax-newpass-123"}
    )
    assert r.status_code == 400
    assert _login("patchtarget", "patchtarget-1pw")["ok"] is True

    # Unknown target -> 404; bad role value -> 400; empty body -> 400.
    assert (
        client.patch("/auth/users/999999", headers=h, json={"displayName": "X"}).status_code
        == 404
    )
    assert (
        client.patch(
            f"/auth/users/{target['id']}", headers=h, json={"role": "superadmin"}
        ).status_code
        == 400
    )
    assert client.patch(f"/auth/users/{target['id']}", headers=h, json={}).status_code == 400

    # SELF-LOCKOUT guard: you cannot deactivate your own account (PATCH or
    # DELETE) — another admin has to do it.
    assert (
        client.patch(f"/auth/users/{admin_id}", headers=h, json={"active": False}).status_code
        == 409
    )
    assert client.delete(f"/auth/users/{admin_id}", headers=h).status_code == 409


# ---------------------------------------------------------------------------
# Disabled-user token death (soft delete + PATCH active=false)
# ---------------------------------------------------------------------------
def test_soft_delete_disabled_user_token_death():
    admin = _login("admin")["accessToken"]
    pw = "ghost1-pass-123"
    ghost = _register(admin, "ghost1", password=pw)
    g = _login("ghost1", pw)
    gh = _h(g["accessToken"])
    assert client.get("/prefs", headers=gh).status_code == 200

    # Baseline generic body for a WRONG password (captured while active).
    bad = client.post("/auth/login", json={"username": "ghost1", "password": "wrong-pass"})
    assert bad.status_code == 401

    assert client.delete(f"/auth/users/{ghost['id']}", headers=_h(admin)).status_code == 204

    # (1) The existing, still-unexpired access token dies at the dependency
    # check on the very next request (live-row read, not JWT claims).
    dead = client.get("/prefs", headers=gh)
    assert dead.status_code == 401
    assert dead.json()["code"] == "unauthorized"
    # (2) Refresh is a credential surface: no new tokens for a disabled user.
    assert (
        client.post("/auth/refresh", json={"refreshToken": g["refreshToken"]}).status_code
        == 401
    )
    # (3) Login with the CORRECT password is refused with the IDENTICAL
    # generic body as a wrong password — no "this account exists but is
    # disabled" oracle (the bcrypt verify still ran first; see routers/auth).
    dis = client.post("/auth/login", json={"username": "ghost1", "password": pw})
    assert dis.status_code == 401
    assert dis.json() == bad.json()

    # Soft, not hard: the row survives with active=false and every refresh
    # token in the DB is revoked (dead sessions don't linger).
    db = SessionLocal()
    try:
        row = db.query(models.User).filter(models.User.username == "ghost1").one()
        assert row.active is False
        tokens = db.query(models.RefreshToken).filter_by(user_id=ghost["id"]).all()
        assert tokens and all(t.revoked for t in tokens)
    finally:
        db.close()

    # Idempotent second DELETE: 204 and NO duplicate deactivate audit row.
    def _deacts():
        return [
            r
            for r in _audit_rows("user_admin")
            if (r.detail or {}).get("op") == "deactivate"
            and (r.detail or {}).get("targetUsername") == "ghost1"
        ]

    assert len(_deacts()) == 1
    assert client.delete(f"/auth/users/{ghost['id']}", headers=_h(admin)).status_code == 204
    assert len(_deacts()) == 1

    # Reactivation (PATCH active=true) restores login.
    r = client.patch(
        f"/auth/users/{ghost['id']}", headers=_h(admin), json={"active": True}
    )
    assert r.status_code == 200
    assert _login("ghost1", pw)["ok"] is True


def test_patch_deactivate_kills_live_session():
    admin = _login("admin")["accessToken"]
    pw = "ghost2-pass-123"
    u = _register(admin, "ghost2", password=pw)
    s = _login("ghost2", pw)
    assert client.get("/prefs", headers=_h(s["accessToken"])).status_code == 200

    r = client.patch(f"/auth/users/{u['id']}", headers=_h(admin), json={"active": False})
    assert r.status_code == 200
    assert r.json()["user"]["active"] is False

    # Same-token next request refused + refresh refused + rows revoked.
    assert client.get("/prefs", headers=_h(s["accessToken"])).status_code == 401
    assert (
        client.post("/auth/refresh", json={"refreshToken": s["refreshToken"]}).status_code
        == 401
    )
    db = SessionLocal()
    try:
        tokens = db.query(models.RefreshToken).filter_by(user_id=u["id"]).all()
        assert tokens and all(t.revoked for t in tokens)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Change password: self OR admin; sessions revoked; nothing leaks to audit
# ---------------------------------------------------------------------------
def test_change_password_matrix():
    admin = _login("admin")["accessToken"]
    pw0 = "pwself-first-1"
    u = _register(admin, "pwself", password=pw0)
    s = _login("pwself", pw0)
    h_self = _h(s["accessToken"])

    # A bystander (not self, not admin role) -> 403; and the SAME 403 for an
    # id that does not exist — permission is checked before existence, so a
    # non-admin cannot enumerate user ids from the 403/404 split.
    officer = _login("officer")["accessToken"]
    assert (
        client.post(
            f"/auth/users/{u['id']}/password",
            headers=_h(officer),
            json={"password": "bystander-set-1"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/auth/users/999999/password", headers=_h(officer), json={"password": "whatever-12"}
        ).status_code
        == 403
    )
    # Admin on a missing id gets the truthful 404; too-short -> 400.
    assert (
        client.post(
            "/auth/users/999999/password", headers=_h(admin), json={"password": "whatever-12"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/auth/users/{u['id']}/password", headers=h_self, json={"password": "short"}
        ).status_code
        == 400
    )

    # SELF change (legacy `newPassword` alias accepted).
    pw1 = "pwself-second-1"
    ok = client.post(f"/auth/users/{u['id']}/password", headers=h_self, json={"newPassword": pw1})
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}
    # Every outstanding refresh token for the target is revoked...
    assert (
        client.post("/auth/refresh", json={"refreshToken": s["refreshToken"]}).status_code
        == 401
    )
    # ...while the short-TTL access token deliberately rides out its lifetime.
    assert client.get("/prefs", headers=h_self).status_code == 200
    # Old credential dead, new credential live.
    old = client.post("/auth/login", json={"username": "pwself", "password": pw0})
    assert old.status_code == 401
    assert _login("pwself", pw1)["ok"] is True

    # ADMIN reset of another user's password.
    pw2 = "pwself-third-1"
    ok2 = client.post(f"/auth/users/{u['id']}/password", headers=_h(admin), json={"password": pw2})
    assert ok2.status_code == 200
    assert _login("pwself", pw2)["ok"] is True

    # The audit chain recorded the changes but NEVER any password material.
    rows = _audit_rows("user_admin")
    changes = [
        r for r in rows if (r.detail or {}).get("op") == "password_change"
        and (r.detail or {}).get("targetUsername") == "pwself"
    ]
    assert len(changes) == 2
    assert changes[0].detail.get("self") is True and changes[0].officer == "pwself"
    assert changes[1].detail.get("self") is False and changes[1].officer == "admin"
    blob = json.dumps(
        [{"notes": r.notes, "detail": r.detail} for r in rows], default=str
    )
    for secret in (pw0, pw1, pw2):
        assert secret not in blob


# ---------------------------------------------------------------------------
# Audit rows on user mutations (register / update / password / deactivate)
# ---------------------------------------------------------------------------
def test_audit_rows_on_user_mutations():
    from gateway import audit as audit_mod

    admin = _login("admin")["accessToken"]
    before = len(_audit_rows("user_admin"))

    u = _register(admin, "audituser", password="audituser-1pw")
    assert (
        client.patch(
            f"/auth/users/{u['id']}", headers=_h(admin), json={"displayName": "Audit User"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/auth/users/{u['id']}/password", headers=_h(admin), json={"password": "audituser-2pw"}
        ).status_code
        == 200
    )
    assert client.delete(f"/auth/users/{u['id']}", headers=_h(admin)).status_code == 204

    new = _audit_rows("user_admin")[before:]
    assert [(r.detail or {}).get("op") for r in new] == [
        "register",
        "update",
        "password_change",
        "deactivate",
    ]
    # officer comes from the TOKEN (server-side), target is recorded, the
    # auditRef carries the user-admin code, violation_id stays empty.
    assert all(r.officer == "admin" for r in new)
    assert all((r.detail or {}).get("targetUsername") == "audituser" for r in new)
    assert all(r.id.startswith("AUD-USR") for r in new)
    assert all((r.violation_id or "") == "" for r in new)
    assert new[1].detail.get("fields") == ["display_name"]

    # The chain still verifies end-to-end after the burst of mutations.
    db = SessionLocal()
    try:
        assert audit_mod.verify_chain(db)["ok"] is True
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Prefs: own-row partial update + isolation between users
# ---------------------------------------------------------------------------
def test_prefs_partial_update_own_row():
    assert client.get("/prefs").status_code == 401  # authn required

    admin = _login("admin")["accessToken"]
    pw = "prefu1-pass-1"
    _register(admin, "prefu1", password=pw)
    h = _h(_login("prefu1", pw)["accessToken"])

    assert client.get("/prefs", headers=h).json() == {
        "ok": True,
        "preferences": {},
        "keybinds": {},
        "theme": "dark",
    }
    # theme-only PUT leaves preferences/keybinds untouched...
    r = client.put("/prefs", headers=h, json={"theme": "light"})
    assert r.status_code == 200
    assert r.json()["theme"] == "light" and r.json()["preferences"] == {}
    # ...preferences-only PUT keeps the theme...
    r2 = client.put("/prefs", headers=h, json={"preferences": {"volume": 5}})
    assert r2.json()["theme"] == "light"
    assert r2.json()["preferences"] == {"volume": 5}
    # ...keybinds-only PUT keeps both.
    r3 = client.put("/prefs", headers=h, json={"keybinds": {"approve": "a"}})
    assert r3.json()["keybinds"] == {"approve": "a"}
    assert r3.json()["theme"] == "light"

    # Invalid themes (blank / over the column width) -> 400.
    assert client.put("/prefs", headers=h, json={"theme": "   "}).status_code == 400
    assert client.put("/prefs", headers=h, json={"theme": "x" * 25}).status_code == 400

    # Persisted: a fresh GET (new request/session) sees the same state.
    j = client.get("/prefs", headers=h).json()
    assert j["theme"] == "light"
    assert j["preferences"] == {"volume": 5}
    assert j["keybinds"] == {"approve": "a"}


def test_prefs_isolation_between_users():
    admin = _login("admin")["accessToken"]
    pa, pb = "prefua-pass-1", "prefub-pass-1"
    ua = _register(admin, "prefua", password=pa)
    _register(admin, "prefub", password=pb)
    ta = _h(_login("prefua", pa)["accessToken"])
    tb = _h(_login("prefub", pb)["accessToken"])

    # A writes; B's row is untouched (still defaults).
    r = client.put(
        "/prefs",
        headers=ta,
        json={"theme": "solar", "preferences": {"owner": "a"}, "keybinds": {"k": "a"}},
    )
    assert r.status_code == 200
    jb = client.get("/prefs", headers=tb).json()
    assert jb["theme"] == "dark" and jb["preferences"] == {} and jb["keybinds"] == {}

    # B writes different values; A keeps its own.
    client.put("/prefs", headers=tb, json={"theme": "mono", "preferences": {"owner": "b"}})
    ja = client.get("/prefs", headers=ta).json()
    assert ja["theme"] == "solar" and ja["preferences"] == {"owner": "a"}

    # There is NO cross-user surface: a client-supplied userId in the body is
    # dead weight (permissive schema tolerates it, handler never reads it) —
    # the write still lands on the CALLER's row only.
    sneaky = client.put("/prefs", headers=tb, json={"userId": ua["id"], "theme": "stolen"})
    assert sneaky.status_code == 200
    assert client.get("/prefs", headers=ta).json()["theme"] == "solar"
    assert client.get("/prefs", headers=tb).json()["theme"] == "stolen"

    # Belt-and-suspenders: the rows in the DB really are per-user.
    db = SessionLocal()
    try:
        rows = {
            u.username: u
            for u in db.query(models.User)
            .filter(models.User.username.in_(["prefua", "prefub"]))
            .all()
        }
        assert rows["prefua"].theme == "solar"
        assert rows["prefua"].preferences == {"owner": "a"}
        assert rows["prefub"].theme == "stolen"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Services: read for any authenticated user, admin-only allowlisted PATCH,
# audited; system status tolerates an empty table
# ---------------------------------------------------------------------------
def test_services_matrix_allowlist_and_audit():
    assert client.get("/services").status_code == 401  # authn required

    officer = _login("officer")["accessToken"]
    supervisor = _login("supervisor")["accessToken"]
    admin = _login("admin")["accessToken"]

    r = client.get("/services", headers=_h(officer))
    assert r.status_code == 200
    services = r.json()["services"]
    assert len(services) >= 6  # seeded board
    svc = services[0]
    assert {"id", "name", "status", "detail", "uptime", "latency", "usage", "updatedAt"} <= set(
        svc
    )
    sid = svc["id"]

    # PATCH is admin-ROLE-only: officer and supervisor both 403.
    for tok in (officer, supervisor):
        denied = client.patch(f"/services/{sid}", headers=_h(tok), json={"status": "down"})
        assert denied.status_code == 403
        assert denied.json()["code"] == "forbidden"

    # Admin PATCH: allowlisted fields change; non-allowlisted keys (name/id)
    # are ignored even though the permissive schema tolerates them; the write
    # is audited with the actor from the token.
    before = len(_audit_rows("service_change"))
    ok = client.patch(
        f"/services/{sid}",
        headers=_h(admin),
        json={"status": "maintenance", "latency": "123ms", "name": "hax-renamed", "id": 424242},
    )
    assert ok.status_code == 200
    body = ok.json()["service"]
    assert body["status"] == "maintenance" and body["latency"] == "123ms"
    assert body["name"] == svc["name"] and body["id"] == sid  # allowlist held

    rows = _audit_rows("service_change")
    assert len(rows) == before + 1
    assert rows[-1].officer == "admin"
    assert rows[-1].id.startswith("AUD-SVC")
    assert (rows[-1].detail or {}).get("serviceId") == sid
    assert sorted((rows[-1].detail or {}).get("fields", [])) == ["latency", "status"]

    # Empty patch -> 400 (no valid fields); unknown id -> 404.
    assert client.patch(f"/services/{sid}", headers=_h(admin), json={}).status_code == 400
    assert (
        client.patch("/services/999999", headers=_h(admin), json={"status": "x"}).status_code
        == 404
    )


def test_system_status_and_empty_table():
    assert client.get("/system/status").status_code == 401  # authn required

    t = _login("officer")["accessToken"]
    r = client.get("/system/status", headers=_h(t))
    assert r.status_code == 200
    row = r.json()["row"]
    assert row is not None  # seeded snapshot
    assert {"id", "timestamp", "status", "detail"} <= set(row)

    # A fresh, un-seeded DB has NO system_status rows — that is a valid state
    # and must answer {ok, row: null}, not 500. Empty the table, assert, then
    # restore the snapshot for any later reader.
    db = SessionLocal()
    try:
        saved = [
            (s.status, s.detail, s.timestamp) for s in db.query(models.SystemStatus).all()
        ]
        db.query(models.SystemStatus).delete()
        db.commit()

        empty = client.get("/system/status", headers=_h(t))
        assert empty.status_code == 200
        assert empty.json() == {"ok": True, "row": None}

        for status, detail, ts in saved:
            db.add(models.SystemStatus(status=status, detail=detail, timestamp=ts))
        db.commit()
    finally:
        db.close()

    restored = client.get("/system/status", headers=_h(t))
    assert restored.json()["row"] is not None
