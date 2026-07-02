"""Own-user preferences (the renderer's prefs:load / prefs:save IPC pair).

GET /prefs  -> { ok, preferences, keybinds, theme }
PUT /prefs  -> partial update of {preferences, keybinds, theme}, same shape back

The target row is ALWAYS the authenticated user from the bearer token — there
is deliberately no /prefs/{userId} surface, so one user can never read or
write another's preferences (the legacy IPC trusted a client-supplied userId).

No audit rows here: prefs are the caller's own cosmetic state (theme,
keybinds), not a security-relevant mutation — the audit chain stays signal,
not noise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..schemas import PrefsPut
from ..security import current_user

router = APIRouter(tags=["Prefs"])

_MAX_THEME_LEN = 24  # users.theme column width


def _prefs_json(u: models.User) -> dict:
    # Mirrors the legacy prefs:load response shape.
    return {
        "ok": True,
        "preferences": u.preferences or {},
        "keybinds": u.keybinds or {},
        "theme": u.theme or "dark",
    }


@router.get("/prefs")
def get_prefs(user: models.User = Depends(current_user)) -> dict:
    return _prefs_json(user)


@router.put("/prefs")
def put_prefs(
    req: PrefsPut,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Partial update: only the provided keys change (PUT {theme} leaves
    preferences/keybinds untouched). current_user and this handler share the
    request-scoped session (FastAPI dependency cache), so the mutation commits
    on the row the token authenticated."""
    if req.theme is not None:
        theme = req.theme.strip()
        if not theme or len(theme) > _MAX_THEME_LEN:
            raise HTTPException(status_code=400, detail="Invalid theme")
        user.theme = theme
    if req.preferences is not None:
        user.preferences = req.preferences
    if req.keybinds is not None:
        user.keybinds = req.keybinds
    db.commit()
    return _prefs_json(user)
