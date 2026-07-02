"""User management + credential administration.

POST   /auth/register             admin ROLE + canManageUsers PRIVILEGE
GET    /auth/users                canManageUsers
PATCH  /auth/users/{id}           canManageUsers; setting role/privileges
                                  additionally requires the admin ROLE
                                  (privilege-escalation guard)
POST   /auth/users/{id}/password  self OR admin role
DELETE /auth/users/{id}           canManageUsers; SOFT delete (active=false)

Design notes:
  * PATCH NEVER accepts a password — the change-password endpoint is the only
    credential write path, and it always bcrypt-hashes IN the gateway (a hash
    or plaintext never round-trips).
  * Deactivation (PATCH active=false or DELETE) is IMMEDIATE, mirroring the
    dispatch gateway's disabled-officer pattern: login refuses the account
    with the SAME generic 401 as a bad credential (and only AFTER the
    constant-time bcrypt verify — see routers/auth.py), any already-issued
    access token dies at the next request (security.current_user re-reads the
    live row), and /auth/refresh refuses to mint new tokens.
  * A password change revokes ALL of the target's refresh tokens: an attacker
    (or ex-holder) of an old refresh token cannot ride out a credential reset.
    In-flight access tokens ride out their short TTL.
  * Every mutation writes a SERVER-SIDE audit row (action=user_admin) staged
    via audit.record() and committed in the same transaction as the change.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import audit, models
from ..db import get_db
from ..schemas import PasswordChangeReq, RegisterReq, UserPatch
from ..security import (
    current_user,
    hash_password,
    require_privilege,
    require_roles,
)
from ..util import iso

logger = logging.getLogger("revgw.users")

router = APIRouter(tags=["Users"])

_ROLES = {"admin", "supervisor", "officer"}
_MIN_PASSWORD_LEN = 8

# List / PATCH / DELETE are privilege-gated (live row — revocation immediate).
_manage_gate = require_privilege("canManageUsers")
_admin_role = require_roles("admin")


def _register_gate(
    user: models.User = Depends(_admin_role),
) -> models.User:
    """Register needs the admin ROLE **and** the canManageUsers PRIVILEGE
    (contract). Role alone is not enough — there is no implicit role bypass —
    and privilege alone is not enough either."""
    if (user.privileges or {}).get("canManageUsers") is not True:
        raise HTTPException(
            status_code=403, detail="insufficient privilege for this action"
        )
    return user


def _user_json(u: models.User) -> dict:
    # Superset of the legacy auth:list-users columns (id, username,
    # display_name->name, role, privileges, active, created_at, last_login).
    return {
        "id": u.id,
        "username": u.username,
        "name": u.display_name,
        "role": u.role,
        "privileges": u.privileges or {},
        "active": bool(u.active),
        "createdAt": iso(u.created_at),
        "lastLogin": iso(u.last_login),
    }


def _revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user_id,
        models.RefreshToken.revoked == False,  # noqa: E712
    ).update({"revoked": True}, synchronize_session=False)


@router.post("/auth/register")
def register(
    req: RegisterReq,
    actor: models.User = Depends(_register_gate),
    db: Session = Depends(get_db),
) -> dict:
    username = (req.username or "").strip().lower()
    if not username or len(username) > 64:
        raise HTTPException(status_code=400, detail="Invalid username")
    if len(req.password or "") < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LEN} characters",
        )
    role = (req.role or "officer").strip().lower()
    if role not in _ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = (
        db.query(models.User).filter(models.User.username == username).one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = models.User(
        username=username,
        password_hash=hash_password(req.password),  # bcrypt IN the gateway
        display_name=(req.display_name or "").strip(),
        role=role,
        privileges=req.privileges or {},
        active=True,
    )
    db.add(user)
    db.flush()  # assign user.id for the audit detail
    audit.record(
        db,
        officer=actor.username,
        action="user_admin",
        notes=f"registered user '{username}' (role={role})",
        detail={
            "op": "register",
            "targetUserId": user.id,
            "targetUsername": username,
            "role": role,
        },
    )
    db.commit()
    logger.info("user registered username=%s by=%s", username, actor.username)
    return {"ok": True, "user": _user_json(user)}


@router.get("/auth/users")
def list_users(
    actor: models.User = Depends(_manage_gate),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.query(models.User).order_by(models.User.id.asc()).all()
    return {"ok": True, "users": [_user_json(u) for u in rows]}


@router.patch("/auth/users/{user_id}")
def update_user(
    user_id: int,
    req: UserPatch,
    actor: models.User = Depends(_manage_gate),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    changes: dict = {}
    if req.display_name is not None:
        changes["display_name"] = req.display_name.strip()
    if req.role is not None:
        role = req.role.strip().lower()
        if role not in _ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        changes["role"] = role
    if req.privileges is not None:
        changes["privileges"] = req.privileges
    if req.active is not None:
        changes["active"] = bool(req.active)
    if not changes:
        # Mirrors the legacy handler's "No valid fields" (and note: a
        # "password" key is NOT a valid field here by design).
        raise HTTPException(status_code=400, detail="No valid fields")

    # ESCALATION GUARD: granting roles or privileges is admin-only. Without
    # this, any canManageUsers holder could promote THEMSELVES to admin /
    # grant themselves every privilege.
    if ("role" in changes or "privileges" in changes) and actor.role != "admin":
        raise HTTPException(
            status_code=403, detail="insufficient role for this action"
        )

    # SELF-LOCKOUT GUARD: you cannot deactivate your own account (an admin
    # locking themselves out mid-session; another admin can still do it).
    if changes.get("active") is False and target.id == actor.id:
        raise HTTPException(
            status_code=409, detail="Cannot deactivate your own account"
        )

    for k, v in changes.items():
        setattr(target, k, v)
    if changes.get("active") is False:
        # Defense-in-depth: /auth/refresh already refuses inactive users, but
        # dead sessions should not linger as usable-looking rows.
        _revoke_all_refresh_tokens(db, target.id)

    audit.record(
        db,
        officer=actor.username,
        action="user_admin",
        notes=f"updated user '{target.username}' ({', '.join(sorted(changes))})",
        detail={
            "op": "update",
            "targetUserId": target.id,
            "targetUsername": target.username,
            "fields": sorted(changes),
        },
    )
    db.commit()
    return {"ok": True, "user": _user_json(target)}


@router.post("/auth/users/{user_id}/password")
def change_password(
    user_id: int,
    req: PasswordChangeReq,
    actor: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    # Permission BEFORE existence so a non-admin cannot enumerate user ids
    # from the 403/404 split.
    if actor.id != user_id and actor.role != "admin":
        raise HTTPException(
            status_code=403, detail="insufficient role for this action"
        )
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    new_pw = req.password or ""
    if len(new_pw) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LEN} characters",
        )

    target.password_hash = hash_password(new_pw)  # bcrypt IN the gateway
    # A credential reset invalidates every outstanding session for the target:
    # anyone holding an old refresh token (the reason for the reset, perhaps)
    # is cut off. The audit detail NEVER contains password material.
    _revoke_all_refresh_tokens(db, target.id)
    audit.record(
        db,
        officer=actor.username,
        action="user_admin",
        notes=f"changed password for '{target.username}'",
        detail={
            "op": "password_change",
            "targetUserId": target.id,
            "targetUsername": target.username,
            "self": actor.id == target.id,
        },
    )
    db.commit()
    logger.info(
        "password changed target=%s by=%s", target.username, actor.username
    )
    return {"ok": True}


@router.delete("/auth/users/{user_id}", status_code=204)
def deactivate_user(
    user_id: int,
    actor: models.User = Depends(_manage_gate),
    db: Session = Depends(get_db),
) -> None:
    """SOFT delete: active=false. The row (and its audit lineage) is preserved;
    login + existing tokens die immediately via the live-row checks."""
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == actor.id:
        raise HTTPException(
            status_code=409, detail="Cannot deactivate your own account"
        )
    if target.active:  # idempotent: a second DELETE is a no-op 204, no dup audit
        target.active = False
        _revoke_all_refresh_tokens(db, target.id)
        audit.record(
            db,
            officer=actor.username,
            action="user_admin",
            notes=f"deactivated user '{target.username}'",
            detail={
                "op": "deactivate",
                "targetUserId": target.id,
                "targetUsername": target.username,
            },
        )
        db.commit()
    return None
