"""bcrypt + JWT (access/refresh with jti) + live-row auth dependencies.

Uses a review-gateway-specific HS256 secret so review-desk tokens form an
isolated trust domain — they are NOT valid against the dispatch gateway (or
anything else). Login is USERNAME-based (review desks have no badge numbers)
and there is deliberately NO device attestation: review desktops have no
enrolled device keys, so carrying the HMAC scheme here would be dead code.

Authorization reads the LIVE user row on every request (role + privilege
dict), never the JWT claims — so a privilege revocation or a soft-delete
(active=false) takes effect on the very next request instead of waiting for
the 15-min access token to expire.
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
import time

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .db import get_db

_ALG = "HS256"
_MIN_SECRET_BYTES = 32
_secret_cache: bytes | None = None


def _decode_secret_value(value: str) -> bytes:
    """Decode injected raw secret material — try base64, then hex, then utf-8.

    Requires >=32 bytes of material so a short/weak value can't slip through.
    """
    v = value.strip()
    # base64 (accept standard + urlsafe). Only base64.b64decode takes validate=;
    # urlsafe_b64decode does NOT, so passing it would raise TypeError (and a
    # passphrase-style secret would 500 instead of falling through to utf-8).
    for decoder, kwargs in (
        (base64.b64decode, {"validate": True}),
        (base64.urlsafe_b64decode, {}),
    ):
        try:
            raw = decoder(v, **kwargs)
            if len(raw) >= _MIN_SECRET_BYTES:
                return raw
        except (binascii.Error, ValueError):
            pass
    # hex
    try:
        raw = bytes.fromhex(v)
        if len(raw) >= _MIN_SECRET_BYTES:
            return raw
    except ValueError:
        pass
    # utf-8 passphrase
    raw = v.encode("utf-8")
    if len(raw) >= _MIN_SECRET_BYTES:
        return raw
    raise RuntimeError(
        "GWREV_JWT_SECRET_VALUE is too short; provide >=32 bytes of "
        "base64/hex/utf-8 secret material"
    )


def _secret() -> bytes:
    """Resolve the HS256 signing secret, highest precedence first.

    (a) GWREV_JWT_SECRET_VALUE — raw material injected by env (base64/hex/utf-8)
    (b) the secret file at jwt_secret_path if it exists and is >=32 bytes
    (c) prod (GWREV_ENV=prod) with neither -> RuntimeError; we NEVER
        auto-generate in prod (a per-replica/per-redeploy random secret
        silently invalidates every outstanding token)
    (d) dev fallback — atomically auto-generate and persist the file
    """
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    if settings.jwt_secret_value:
        _secret_cache = _decode_secret_value(settings.jwt_secret_value)
        return _secret_cache

    p = settings.jwt_secret_path
    if p.is_file() and p.stat().st_size >= _MIN_SECRET_BYTES:
        _secret_cache = p.read_bytes()
        return _secret_cache

    if settings.env == "prod":
        raise RuntimeError(
            "JWT secret not provisioned; set GWREV_JWT_SECRET_VALUE or mount "
            "the secret file at GWREV_JWT_SECRET"
        )

    # Dev fallback: auto-generate and persist atomically.
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(32)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass  # Windows / restricted FS — best effort
    _secret_cache = raw
    return raw


# ---- passwords ----
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


# ---- tokens ----
def _issue(
    sub: str, typ: str, ttl: int, extra: dict | None = None
) -> tuple[str, int, str]:
    now = int(time.time())
    # jti makes every token unique even for two logins in the same second
    # (HS256 is deterministic, so without it identical claims -> identical
    # token, which collides on the refresh_tokens PK). It's also the
    # rotation/lineage handle persisted on the refresh_tokens row.
    jti = secrets.token_hex(16)
    payload = {"sub": sub, "typ": typ, "iat": now, "exp": now + ttl, "jti": jti}
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, _secret(), algorithm=_ALG)
    if isinstance(token, bytes):
        token = token.decode("ascii")
    return token, ttl, jti


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    # role rides along for diagnostics only — authz always re-reads the live
    # user row (see current_user / require_privilege).
    token, ttl, _ = _issue(str(user_id), "access", settings.access_ttl_sec, {"role": role})
    return token, ttl


def create_refresh_token(user_id: int) -> tuple[str, str]:
    """Mint a refresh token. Returns (token, jti) — the jti is persisted on the
    refresh_tokens row for rotation lineage and diagnostics."""
    token, _, jti = _issue(str(user_id), "refresh", settings.refresh_ttl_sec)
    return token, jti


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALG])
    except jwt.PyJWTError:
        return None


# ---- auth dependencies ----
def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    claims = decode_token(authorization.split(" ", 1)[1].strip())
    if not claims or claims.get("typ") != "access":
        raise HTTPException(status_code=401, detail="invalid or expired token")
    try:
        uid = int(claims.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid or expired token")
    user = db.get(models.User, uid)
    if user is None:
        raise HTTPException(status_code=401, detail="unknown user")
    # An inactive (soft-deleted) user is rejected even with a still-valid
    # access token, so deactivation takes effect immediately rather than
    # waiting for the TTL.
    if not user.active:
        raise HTTPException(status_code=401, detail="account disabled")
    return user


def require_roles(*needed: str):
    """Dependency factory: gate an endpoint on the user's LIVE DB role.

    Reads the role off the freshly-loaded User row (not the JWT claim) so a
    demotion takes effect on the very next request. Returns the user so
    handlers keep their ``user: models.User = Depends(require_roles(...))``
    signature."""

    wanted = set(needed)

    def _dep(user: models.User = Depends(current_user)) -> models.User:
        if (user.role or "") not in wanted:
            raise HTTPException(
                status_code=403, detail="insufficient role for this action"
            )
        return user

    return _dep


def require_privilege(*names: str, mode: str = "any"):
    """Dependency factory: gate an endpoint on the user's LIVE privilege dict.

    Privileges are the explicit bool flags on the users row (canApprove,
    canDismiss, canRevise, canManageUsers, canManageCameras, canViewAudit,
    canExport). There is NO implicit role bypass — an admin gets access because
    the admin row carries the privilege, not because of the role string.
    mode="any" (default) needs one of ``names``; mode="all" needs every one.
    Reads the live row so revocation is immediate."""

    def _dep(user: models.User = Depends(current_user)) -> models.User:
        privs = user.privileges or {}
        have = [n for n in names if privs.get(n) is True]
        ok = bool(have) if mode == "any" else len(have) == len(names)
        if not ok:
            raise HTTPException(
                status_code=403, detail="insufficient privilege for this action"
            )
        return user

    return _dep
