"""Review-gateway settings — all overridable by env var (GWREV_*) so the same
code runs on the dev SQLite DB or a prod Postgres without edits.

Dev is zero-infra by design: SQLite + local-disk evidence store (exactly like
the dispatch gateway's dev mode). The S3 knobs exist as a LATER seam only —
nothing here connects off-host by default.

Tests patch settings per-test via ``dataclasses.replace`` on the importing
module's ``settings`` object (env vars set inside test functions are ignored
because this module loads at first import).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_GATEWAY_DIR = Path(__file__).resolve().parent


def _data_dir() -> Path:
    d = _GATEWAY_DIR / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class Settings:
    db_url: str
    # Deployment environment. "prod" forbids auto-generating the JWT secret and
    # makes seed() refuse to run.
    env: str
    # Dev-only opt-in (GWREV_SEED=1): seed users/violations/cameras on startup.
    seed_on_start: bool
    # ---- auth ----
    # On-disk HS256 secret file (auto-generated in dev, mandatory mount in prod).
    jwt_secret_path: Path
    # Raw JWT secret material injected via env (base64/hex/utf-8). Takes
    # precedence over the file; one of the two is REQUIRED in prod so we never
    # silently auto-generate a per-replica secret that invalidates every
    # outstanding token.
    jwt_secret_value: str
    access_ttl_sec: int
    refresh_ttl_sec: int
    # Honour X-Forwarded-For's first hop when deriving the client IP for login
    # throttling (only behind a trusted reverse proxy). Off by default so
    # dev / TestClient keys by request.client.host.
    trust_proxy: bool
    # Login brute-force throttle thresholds (seconds for the *_sec fields).
    login_max_failures: int
    login_window_sec: int
    login_lockout_sec: int
    login_user_lockout_sec: int
    # ---- audit immutability ----
    # Key the audit hash chain with HMAC under the gateway secret instead of a
    # plain sha256. Off in dev (tests stay deterministic without the secret
    # file), recommended ON in prod (GWREV_AUDIT_HMAC=1) so a DB writer cannot
    # forge a valid chain without the key.
    audit_hmac: bool
    # ---- evidence object store ----
    # "local" (default) keeps the zero-infra disk behaviour so dev/test/seed
    # never need boto3 or AWS; "s3" selects the lazy-boto3 store (config-only
    # switch, wired later — NO external connection is made by default).
    evidence_store: str
    evidence_dir: Path
    # Absolute base URL of THIS gateway as the app reaches it (e.g.
    # http://127.0.0.1:8090). Local presigned URLs are built from this. Empty
    # default keeps URLs relative for same-origin/test callers.
    public_base_url: str
    # S3/MinIO knobs (S3Store only; unused by the default local store).
    s3_endpoint_url: str
    s3_bucket: str
    s3_region: str
    s3_access_key: str
    s3_secret_key: str
    # Lifetime (seconds) of a presigned evidence URL (matches the 3600s the
    # Electron main process used for its own presigner).
    evidence_url_ttl_sec: int
    # ---- request hygiene ----
    # Hard cap on a request body size (bytes), enforced from Content-Length in
    # the request middleware -> 413 payload_too_large.
    max_body_bytes: int
    # ---- citation-lifecycle bridge push worker (decision_outbox -> dispatch
    # gateway's POST /citations/from-review; see gateway_api_contract.md) ----
    # Base URL of the DISPATCH gateway (e.g. http://127.0.0.1:8088). Empty
    # (default) disables the worker entirely — no task is started, nothing is
    # ever POSTed anywhere by default.
    bridge_url: str
    # Shared secret sent as X-Bridge-Secret. Empty disables the worker (same
    # fail-closed posture as GATEWAY_RACK_SECRET on the dispatch side) — NEVER
    # hardcoded, never written to disk by this module.
    bridge_secret: str
    bridge_poll_sec: float
    bridge_batch: int


def _read_secret(file_env: str, value_env: str) -> str:
    """Read a secret from a file path (preferred, keeps it off the env) falling
    back to an inline env var. The file wins when both are set."""
    file_path = os.environ.get(file_env)
    if file_path:
        p = Path(file_path)
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return os.environ.get(value_env, "")


def load_settings() -> Settings:
    db_url = os.environ.get("GWREV_DB_URL") or (
        f"sqlite:///{(_data_dir() / 'review_dev.db').as_posix()}"
    )
    return Settings(
        db_url=db_url,
        env=os.environ.get("GWREV_ENV", "dev"),
        # Seeding is an explicit dev opt-in (GWREV_SEED=1) — never a default.
        seed_on_start=os.environ.get("GWREV_SEED", "0") == "1",
        jwt_secret_path=Path(
            os.environ.get("GWREV_JWT_SECRET")
            or (_GATEWAY_DIR / "config" / "review_gateway_secret.bin")
        ),
        jwt_secret_value=os.environ.get("GWREV_JWT_SECRET_VALUE", ""),
        access_ttl_sec=int(os.environ.get("GWREV_ACCESS_TTL", 15 * 60)),
        refresh_ttl_sec=int(os.environ.get("GWREV_REFRESH_TTL", 30 * 24 * 3600)),
        trust_proxy=os.environ.get("GWREV_TRUST_PROXY", "0") == "1",
        login_max_failures=int(os.environ.get("GWREV_LOGIN_MAX_FAILURES", 5)),
        login_window_sec=int(os.environ.get("GWREV_LOGIN_WINDOW", 60)),
        login_lockout_sec=int(os.environ.get("GWREV_LOGIN_LOCKOUT", 15 * 60)),
        login_user_lockout_sec=int(
            os.environ.get("GWREV_LOGIN_USER_LOCKOUT", 5 * 60)
        ),
        audit_hmac=os.environ.get("GWREV_AUDIT_HMAC", "0") == "1",
        evidence_store=os.environ.get("GWREV_EVIDENCE_STORE", "local"),
        evidence_dir=Path(
            os.environ.get("GWREV_EVIDENCE_DIR")
            or (_data_dir() / "review_evidence")
        ),
        public_base_url=os.environ.get("GWREV_PUBLIC_URL", ""),
        s3_endpoint_url=os.environ.get("GWREV_S3_ENDPOINT", ""),
        s3_bucket=os.environ.get("GWREV_S3_BUCKET", "hope-evidence"),
        s3_region=os.environ.get("GWREV_S3_REGION", "us-east-1"),
        s3_access_key=_read_secret("GWREV_S3_ACCESS_KEY_FILE", "GWREV_S3_ACCESS_KEY"),
        s3_secret_key=_read_secret("GWREV_S3_SECRET_KEY_FILE", "GWREV_S3_SECRET_KEY"),
        evidence_url_ttl_sec=int(os.environ.get("GWREV_EVIDENCE_URL_TTL", 3600)),
        max_body_bytes=int(os.environ.get("GWREV_MAX_BODY_BYTES", 1 * 1024 * 1024)),
        bridge_url=os.environ.get("GWREV_BRIDGE_URL", "").rstrip("/"),
        bridge_secret=os.environ.get("GWREV_BRIDGE_SECRET", ""),
        bridge_poll_sec=float(os.environ.get("GWREV_BRIDGE_POLL_SEC", 5.0)),
        bridge_batch=int(os.environ.get("GWREV_BRIDGE_BATCH", 20)),
    )


settings = load_settings()
