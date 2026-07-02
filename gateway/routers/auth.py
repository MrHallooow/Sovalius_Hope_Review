"""Auth: username login + refresh rotation with family reuse-detection.

POST /auth/login       { username, password } -> AuthResult
POST /auth/refresh     { refreshToken }       -> AuthResult
POST /auth/logout      { refreshToken }       -> 204
POST /auth/logout-all  (bearer)               -> 204

AuthResult: { ok, user{id,username,name,role,privileges,preferences,keybinds,
theme}, accessToken, refreshToken, accessExpiresAtUtc } — the shape the
Electron renderer's auth store expects (plus tokens, which replace the old
direct-Postgres trust model).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import audit, models
from ..config import settings
from ..db import get_db
from ..schemas import LoginReq, LogoutReq, RefreshReq
from ..security import (
    create_access_token,
    create_refresh_token,
    current_user,
    decode_token,
    hash_password,
    verify_password,
)
from ..util import iso

logger = logging.getLogger("revgw.auth")

router = APIRouter(tags=["Auth"])

# A throwaway bcrypt hash so a login for a NON-existent username still pays the
# same bcrypt cost as a wrong-password login — closes the username-enumeration
# timing oracle (bcrypt rounds=12 is the slow part). Computed once at import.
_DUMMY_HASH = hash_password("hope-review-timing-equaliser")


def _client_ip(request: Request) -> str:
    """Derive the throttling key IP. Behind a trusted reverse proxy (prod)
    honour the first hop of X-Forwarded-For; otherwise use the direct peer.
    Off by default (GWREV_TRUST_PROXY) so dev / TestClient keys by
    request.client."""
    if settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _user_json(u: models.User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "name": u.display_name,
        "role": u.role,
        "privileges": u.privileges or {},
        "preferences": u.preferences or {},
        "keybinds": u.keybinds or {},
        "theme": u.theme or "dark",
    }


def _auth_result(db: Session, user: models.User, family_id: str | None = None) -> dict:
    access, ttl = create_access_token(user.id, user.role)
    refresh, jti = create_refresh_token(user.id)
    # A fresh login starts a new rotation family; every subsequent /refresh
    # inherits this family_id so a detected reuse can revoke the whole lineage.
    db.add(
        models.RefreshToken(
            token=refresh,
            jti=jti,
            family_id=family_id or secrets.token_hex(16),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=settings.refresh_ttl_sec),
        )
    )
    db.commit()
    return {
        "ok": True,
        "user": _user_json(user),
        "accessToken": access,
        "refreshToken": refresh,
        "accessExpiresAtUtc": iso(datetime.now(timezone.utc) + timedelta(seconds=ttl)),
    }


@router.post("/auth/login")
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)) -> dict:
    throttle = request.app.state.login_throttle
    username = req.username.strip().lower()
    ip = _client_ip(request)
    wait = throttle.retry_after(username, ip)
    if wait > 0:
        # Locked out: refuse even a correct password until the window passes.
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Retry later.",
            headers={"Retry-After": str(int(wait))},
        )
    user = (
        db.query(models.User).filter(models.User.username == username).one_or_none()
    )
    # Constant-cost: run bcrypt on BOTH paths so a non-existent username can't
    # be distinguished from a wrong password by response latency.
    password_ok = verify_password(
        req.password, user.password_hash if user is not None else _DUMMY_HASH
    )
    # An inactive user is refused with the SAME generic message as a bad
    # credential (don't leak that the username exists / is merely deactivated),
    # and only AFTER the bcrypt verify above so latency is identical either way.
    if user is None or not password_ok or not user.active:
        if throttle.record_failure(username, ip):
            logger.warning("login lockout started username=%s", username)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    throttle.record_success(username, ip)
    user.last_login = models._utcnow()
    # Server-side login audit (AUD-LOG). record() stages; the _auth_result
    # commit below persists it in the same transaction as last_login + the
    # refresh-token row.
    audit.record(
        db,
        officer=user.username,
        action="login",
        detail={"userId": user.id, "role": user.role},
    )
    return _auth_result(db, user)


@router.post("/auth/refresh")
def refresh(req: RefreshReq, db: Session = Depends(get_db)) -> dict:
    claims = decode_token(req.refreshToken)
    row = db.get(models.RefreshToken, req.refreshToken)

    # REUSE DETECTION FIRST: a syntactically valid refresh token whose row is
    # already revoked is a re-presented (rotated-out or logged-out) token —
    # treat it as a compromised lineage and revoke the ENTIRE family.
    if row is not None and row.revoked:
        if row.reused_at is None:
            row.reused_at = models._utcnow()
        if row.family_id:
            db.query(models.RefreshToken).filter(
                models.RefreshToken.family_id == row.family_id
            ).update({"revoked": True}, synchronize_session=False)
        db.commit()
        logger.warning(
            "refresh reuse detected user=%s family=%s token_prefix=%s",
            row.user_id,
            row.family_id,
            req.refreshToken[:12],
        )
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Reject anything malformed, wrong type, unknown, or expired.
    now = datetime.now(timezone.utc)
    if (
        not claims
        or claims.get("typ") != "refresh"
        or row is None
        or _expired(row.expires_at, now)
    ):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    try:
        uid = int(claims.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = db.get(models.User, uid)
    # An inactive user cannot mint fresh access tokens either — refresh is a
    # credential surface, so live revocation applies here too.
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # HAPPY PATH: rotate — mint a fresh refresh token inheriting the family,
    # mark the presented one revoked + rotated, and return the NEW token.
    new_refresh, new_jti = create_refresh_token(user.id)
    db.add(
        models.RefreshToken(
            token=new_refresh,
            jti=new_jti,
            family_id=row.family_id,
            user_id=user.id,
            expires_at=now + timedelta(seconds=settings.refresh_ttl_sec),
        )
    )
    row.revoked = True
    row.rotated_at = models._utcnow()
    row.replaced_by = new_refresh

    access, ttl = create_access_token(user.id, user.role)
    db.commit()
    return {
        "ok": True,
        "user": _user_json(user),
        "accessToken": access,
        "refreshToken": new_refresh,
        "accessExpiresAtUtc": iso(now + timedelta(seconds=ttl)),
    }


def _expired(expires_at: datetime | None, now: datetime) -> bool:
    """Belt-and-suspenders expiry check on the stored row (decode_token already
    rejects an expired JWT, but the DB row is the durable record)."""
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _revoke_family(db: Session, family_id: str) -> None:
    if family_id:
        db.query(models.RefreshToken).filter(
            models.RefreshToken.family_id == family_id
        ).update({"revoked": True}, synchronize_session=False)


@router.post("/auth/logout", status_code=204)
def logout(req: LogoutReq, db: Session = Depends(get_db)) -> None:
    if req.refreshToken:
        row = db.get(models.RefreshToken, req.refreshToken)
        if row is not None:
            # Revoke the whole rotation lineage, not just the presented leaf,
            # so an outstanding ancestor can't be replayed after logout.
            if row.family_id:
                _revoke_family(db, row.family_id)
            else:
                row.revoked = True
            db.commit()
    return None


@router.post("/auth/logout-all", status_code=204)
def logout_all(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    """Revoke every non-revoked refresh token for the authenticated user
    (all sessions)."""
    db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user.id,
        models.RefreshToken.revoked == False,  # noqa: E712
    ).update({"revoked": True}, synchronize_session=False)
    db.commit()
    return None
