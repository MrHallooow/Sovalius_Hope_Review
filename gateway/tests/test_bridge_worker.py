"""Coverage for the citation-lifecycle bridge push worker (step 2 — see
gateway_api_contract.md "Camera citations — the review->service bridge" and
bridge_worker.py's own module docstring for the outcome-handling contract
this module verifies).

Same conventions as test_decision_outbox.py: only pin fresh env when this
module is the FIRST gateway importer (so a full-suite run shares the DB that
whichever module actually runs first bootstrapped); assertions are therefore
delta-scoped / row-scoped, never an absolute row count. The dispatch side is
mocked with httpx.MockTransport — no real dispatch gateway is required.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

if "GWREV_DB_URL" not in os.environ:
    _TMP = tempfile.mkdtemp(prefix="revgw_bridge_test_")
    os.environ["GWREV_DB_URL"] = f"sqlite:///{pathlib.Path(_TMP, 't.db').as_posix()}"
    os.environ["GWREV_JWT_SECRET"] = str(pathlib.Path(_TMP, "secret.bin"))
    os.environ["GWREV_EVIDENCE_DIR"] = str(pathlib.Path(_TMP, "ev"))
os.environ.setdefault("GWREV_SEED", "1")
os.environ.setdefault("GWREV_SEED_PASSWORD", "review1234")

import httpx  # noqa: E402
import pytest  # noqa: E402

from gateway import bridge_worker, config, models  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.db import SessionLocal  # noqa: E402

# Importing the app is enough to initialise the DB (alembic upgrade head) even
# though this module never spins up a TestClient of its own.
create_app()

_ENABLED_CFG = dataclasses.replace(
    config.settings,
    bridge_url="http://bridge.test",
    bridge_secret="s3kret",
    bridge_batch=20,
)


def _mk_row(db, *, decision: str = "approved", **kwargs) -> models.DecisionOutbox:
    defaults = dict(
        violation_id=f"VIO-BRIDGE-{kwargs.pop('suffix', '')}",
        decision=decision,
        payload={
            "violationId": "VIO-BRIDGE",
            "decision": decision,
            "reviewedBy": "Sgt. Williams",
            "reviewedAtUtc": "2026-03-20T09:00:00+00:00",
            "reviewNotes": "",
            "violation": {
                "plate": "SV-1",
                "type": "Speeding",
                "speedMph": 70,
                "speedLimitMph": 50,
                "camera": "CAM-1",
                "capturedAtUtc": "2026-03-20T09:00:00+00:00",
                "location": {"lat": 13.15, "lng": -61.2, "label": "Test Rd"},
                "citable": True,
                "gateReason": "gate: citation class, certified basis",
                "evidence": [],
            },
        },
    )
    defaults.update(kwargs)
    row = models.DecisionOutbox(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _reload(db, row_id: int) -> models.DecisionOutbox:
    db.expire_all()
    return db.get(models.DecisionOutbox, row_id)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=bridge_worker._TIMEOUT)


# ---------------------------------------------------------------------------
# drain_once delivers an approved row on 2xx
# ---------------------------------------------------------------------------
def test_drain_once_delivers_approved_row_on_2xx():
    db = SessionLocal()
    try:
        row = _mk_row(db, suffix="A")
        row_id = row.id

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/citations/from-review"
            assert request.headers["x-bridge-secret"] == "s3kret"
            import json as _json

            body = _json.loads(request.content)
            assert body["sourceEventId"] == row_id
            assert body["violationId"] == "VIO-BRIDGE"  # payload spread verbatim
            return httpx.Response(
                200,
                json={"citationClientId": "C1", "status": "awaiting_service", "duplicate": False},
            )

        with _mock_client(handler) as client:
            n = bridge_worker.drain_once(db, _ENABLED_CFG, client=client)
        assert n == 1

        got = _reload(db, row_id)
        assert got.delivered_at is not None
        assert got.attempts == 1
        assert got.last_error == ""
        assert got.parked_at is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# dismissed / reopened rows are never selected
# ---------------------------------------------------------------------------
def test_dismissed_and_reopened_rows_never_selected():
    db = SessionLocal()
    try:
        dismissed = _mk_row(db, suffix="DISM", decision="dismissed")
        reopened = _mk_row(db, suffix="REOP", decision="reopened")

        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"status": "awaiting_service", "duplicate": False})

        with _mock_client(handler) as client:
            n = bridge_worker.drain_once(db, _ENABLED_CFG, client=client)
        assert n == 0
        assert calls == []

        assert _reload(db, dismissed.id).delivered_at is None
        assert _reload(db, reopened.id).delivered_at is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5xx then 2xx across two drains: delivered on second, attempts==2, backoff
# respected via next_attempt_at (no sleeping — now/next_attempt_at driven).
# ---------------------------------------------------------------------------
def test_5xx_then_2xx_across_two_drains_respects_backoff():
    db = SessionLocal()
    try:
        row = _mk_row(db, suffix="RETRY")
        row_id = row.id

        state = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(500, text="boom")
            return httpx.Response(200, json={"status": "awaiting_service", "duplicate": False})

        t0 = datetime.now(timezone.utc)
        with _mock_client(handler) as client:
            n1 = bridge_worker.drain_once(db, _ENABLED_CFG, client=client, now=t0)
        assert n1 == 1
        got = _reload(db, row_id)
        assert got.delivered_at is None
        assert got.attempts == 1
        assert got.last_error.startswith("500")
        assert got.next_attempt_at is not None
        next_attempt = got.next_attempt_at.replace(tzinfo=timezone.utc)
        assert next_attempt > t0

        # Immediately re-draining at t0 must NOT re-attempt (still backing off).
        with _mock_client(handler) as client:
            n_none = bridge_worker.drain_once(db, _ENABLED_CFG, client=client, now=t0)
        assert n_none == 0
        assert state["n"] == 1

        # Advance past next_attempt_at -> second drain delivers.
        t1 = next_attempt + timedelta(seconds=1)
        with _mock_client(handler) as client:
            n2 = bridge_worker.drain_once(db, _ENABLED_CFG, client=client, now=t1)
        assert n2 == 1

        final = _reload(db, row_id)
        assert final.delivered_at is not None
        assert final.attempts == 2
        assert final.last_error == ""
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 422 non_citable parks the row permanently; excluded from next drain;
# quarantined count reflects it.
# ---------------------------------------------------------------------------
def test_422_non_citable_parks_row_and_is_excluded_thereafter():
    db = SessionLocal()
    try:
        row = _mk_row(db, suffix="PARK")
        row_id = row.id

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"code": "non_citable", "message": "not citable", "retryable": False})

        with _mock_client(handler) as client:
            n = bridge_worker.drain_once(db, _ENABLED_CFG, client=client)
        assert n == 1

        got = _reload(db, row_id)
        assert got.delivered_at is None
        assert got.parked_at is not None
        assert "non_citable" in got.last_error
        assert got.attempts == 1

        # Excluded from the next drain (no further calls made for this row).
        calls = []

        def handler2(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"status": "awaiting_service"})

        with _mock_client(handler2) as client:
            n2 = bridge_worker.drain_once(db, _ENABLED_CFG, client=client)
        assert n2 == 0
        assert calls == []

        snap = bridge_worker.outbox_snapshot(db)
        assert snap["quarantined"] >= 1
    finally:
        db.close()


def test_422_unmapped_offence_also_parks():
    db = SessionLocal()
    try:
        row = _mk_row(db, suffix="PARK2")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"code": "unmapped_offence", "message": "no mapping", "retryable": False})

        with _mock_client(handler) as client:
            bridge_worker.drain_once(db, _ENABLED_CFG, client=client)

        got = _reload(db, row.id)
        assert got.parked_at is not None
        assert got.delivered_at is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# duplicate:true 2xx is still treated as success
# ---------------------------------------------------------------------------
def test_duplicate_true_2xx_treated_as_success():
    db = SessionLocal()
    try:
        row = _mk_row(db, suffix="DUP")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"citationClientId": "C1", "status": "awaiting_service", "duplicate": True},
            )

        with _mock_client(handler) as client:
            n = bridge_worker.drain_once(db, _ENABLED_CFG, client=client)
        assert n == 1

        got = _reload(db, row.id)
        assert got.delivered_at is not None
        assert got.last_error == ""
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Worker disabled when config empty: drain_once refuses (no task, no calls).
# ---------------------------------------------------------------------------
def test_worker_disabled_when_config_empty():
    db = SessionLocal()
    try:
        _mk_row(db, suffix="DISABLED")

        empty_cfg = dataclasses.replace(config.settings, bridge_url="", bridge_secret="")
        assert bridge_worker.is_enabled(empty_cfg) is False

        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={})

        with _mock_client(handler) as client:
            n = bridge_worker.drain_once(db, empty_cfg, client=client)
        assert n == 0
        assert calls == []

        # Also refuses with only ONE of the two set.
        half_cfg = dataclasses.replace(config.settings, bridge_url="http://x", bridge_secret="")
        assert bridge_worker.is_enabled(half_cfg) is False
    finally:
        db.close()


def test_run_forever_not_started_when_disabled():
    """App-level guard: create_app() must not schedule the poll task when the
    worker is disabled (default test env has no GWREV_BRIDGE_URL/SECRET)."""
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as _client:
        # TestClient's context manager drives the lifespan startup/shutdown.
        assert app.state.bridge_worker_task is None


# ---------------------------------------------------------------------------
# select_due — pure function, no DB
# ---------------------------------------------------------------------------
def test_select_due_pure_function():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def _row(**kw):
        base = dict(
            id=1,
            violation_id="V",
            decision="approved",
            payload={},
            created_at=now - timedelta(hours=1),
            delivered_at=None,
            attempts=0,
            last_error="",
            parked_at=None,
            next_attempt_at=None,
        )
        base.update(kw)
        return models.DecisionOutbox(**base)

    due_row = _row(id=1)
    delivered_row = _row(id=2, delivered_at=now)
    parked_row = _row(id=3, parked_at=now)
    dismissed_row = _row(id=4, decision="dismissed")
    not_yet_row = _row(id=5, next_attempt_at=now + timedelta(minutes=5))
    now_due_row = _row(id=6, next_attempt_at=now - timedelta(seconds=1))

    result = bridge_worker.select_due(
        [due_row, delivered_row, parked_row, dismissed_row, not_yet_row, now_due_row], now
    )
    ids = [r.id for r in result]
    assert ids == [1, 6]  # oldest (by created_at) first; both share created_at so id tie-break


def test_compute_backoff_sec_bounds():
    # attempt 1: base*2^1=10s plus up to 20% jitter -> [10, 12]
    v1 = bridge_worker.compute_backoff_sec(1)
    assert 10.0 <= v1 <= 12.0 + 1e-9
    # Very high attempt count is capped at 15min * 1.2
    v_big = bridge_worker.compute_backoff_sec(100)
    assert v_big <= 15 * 60 * 1.2 + 1e-9


# ---------------------------------------------------------------------------
# system status exposes the outbox block with correct counts
# ---------------------------------------------------------------------------
def test_outbox_snapshot_counts_only_approved_unparked():
    db = SessionLocal()
    try:
        before = bridge_worker.outbox_snapshot(db)

        _mk_row(db, suffix="SNAP-APPROVED")
        _mk_row(db, suffix="SNAP-DISMISSED", decision="dismissed")

        after = bridge_worker.outbox_snapshot(db)
        assert after["undelivered"] == before["undelivered"] + 1  # only the approved row
        assert after["oldest_undelivered_age_sec"] is not None
        assert after["oldest_undelivered_age_sec"] >= 0
    finally:
        db.close()


def test_system_status_endpoint_exposes_outbox_block():
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    r = client.post(
        "/auth/login", json={"username": "officer", "password": "review1234"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["accessToken"]

    resp = client.get(
        "/system/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "outbox" in body
    assert {
        "undelivered",
        "quarantined",
        "oldest_undelivered_age_sec",
        "last_error",
    } <= set(body["outbox"])


def test_run_forever_survives_a_failing_drain_pass(monkeypatch):
    """A transient failure inside one drain pass (DB hiccup, unexpected bug)
    must NOT kill the lifespan task — a dead worker is indistinguishable from
    an idle one from the outside. The loop logs and keeps polling."""
    import asyncio

    calls: list[int] = []

    async def flaky(db, cfg, *, client=None, now=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated transient drain failure")
        return 0

    monkeypatch.setattr(bridge_worker, "adrain_once", flaky)
    cfg = dataclasses.replace(_ENABLED_CFG, bridge_poll_sec=0.01)

    async def scenario():
        task = asyncio.create_task(bridge_worker.run_forever(cfg))
        try:
            async with asyncio.timeout(5):
                while len(calls) < 3:
                    await asyncio.sleep(0.01)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # The task survived the first (raising) pass and kept polling.
        assert len(calls) >= 3

    asyncio.run(scenario())
