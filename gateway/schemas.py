"""Pydantic v2 request models — PERMISSIVE by design.

Every model uses ``ConfigDict(extra="allow")`` so unknown keys from a newer
renderer build still validate (the handlers only read the declared fields).
The RequestValidationError handler in app.py returns the TOP-LEVEL
{code:'invalid', ...} body the Electron app's error mapping parses, so a
validation failure stays app-compatible with no handler change.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class _Permissive(BaseModel):
    """Base: tolerate unknown keys so client evolution never 400s."""

    model_config = ConfigDict(extra="allow")


class LoginReq(_Permissive):
    username: str
    password: str


class RefreshReq(_Permissive):
    refreshToken: str


class LogoutReq(_Permissive):
    refreshToken: str | None = None


class ReviewPatch(_Permissive):
    """PATCH /violations/{id}/review — reviewed_by / reviewed_at are NEVER
    accepted from the client (server sets them from the token + server time)."""

    status: str | None = None
    notes: str | None = None
    pinned: bool | None = None


class NotificationPatch(_Permissive):
    """PATCH /notifications/{id} — optional body; omitted/None read means
    "mark read" (the legacy db:mark-notification-read IPC sent no payload)."""

    read: bool | None = None


class CameraPatch(_Permissive):
    """PATCH /cameras/{id} — server-side ALLOWLIST, unlike the legacy IPC
    handler which interpolated arbitrary client-supplied column names into
    SQL. Only these mutable fields exist; anything else is ignored."""

    location: str | None = None
    status: str | None = None


class LanesPut(_Permissive):
    """PUT /cameras/{name}/lanes — UPSERT body. Accepts the renderer's
    camelCase names plus the legacy IPC snake/short names (laneData /
    lane_data, calibrationWidth / calWidth, ...)."""

    lane_data: dict | list = Field(
        default_factory=dict,
        validation_alias=AliasChoices("laneData", "lane_data"),
    )
    calibration_width: int = Field(
        0,
        validation_alias=AliasChoices(
            "calibrationWidth", "calibration_width", "calWidth"
        ),
    )
    calibration_height: int = Field(
        0,
        validation_alias=AliasChoices(
            "calibrationHeight", "calibration_height", "calHeight"
        ),
    )


class RegisterReq(_Permissive):
    """POST /auth/register — the gateway bcrypt-hashes ``password``; a hash
    never round-trips through the API. Accepts both displayName (the legacy
    auth:register IPC arg name) and display_name."""

    username: str
    password: str
    display_name: str = Field(
        "", validation_alias=AliasChoices("displayName", "display_name")
    )
    role: str = "officer"
    privileges: dict = Field(default_factory=dict)


class UserPatch(_Permissive):
    """PATCH /auth/users/{id} — deliberately NO password field: the
    change-password endpoint is the ONLY credential write path. A stray
    "password" key in the body is tolerated (permissive base) but never read."""

    display_name: str | None = Field(
        None, validation_alias=AliasChoices("displayName", "display_name")
    )
    role: str | None = None
    privileges: dict | None = None
    active: bool | None = None


class PasswordChangeReq(_Permissive):
    """POST /auth/users/{id}/password — ``password`` preferred; ``newPassword``
    accepted for parity with the legacy auth:change-password IPC arg name."""

    password: str | None = Field(
        None, validation_alias=AliasChoices("password", "newPassword")
    )


class PrefsPut(_Permissive):
    """PUT /prefs — partial update of the CALLER's own row only (the target
    user always comes from the token, never from the body)."""

    preferences: dict | None = None
    keybinds: dict | None = None
    theme: str | None = None


class ServicePatch(_Permissive):
    """PATCH /services/{id} — server-side ALLOWLIST (the legacy IPC handler
    interpolated arbitrary client column names into SQL; these five are the
    only mutable fields)."""

    status: str | None = None
    detail: str | None = None
    uptime: str | None = None
    latency: str | None = None
    usage: str | None = None
