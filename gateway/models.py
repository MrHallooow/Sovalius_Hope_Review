"""Review-gateway ORM — the schema the Electron review app's IPC handlers
implied (verified against electron/main.js + schema.sql + setup-*.js).

Portability notes vs the legacy Postgres schema:
  * ``violations.cameras`` was Postgres ``TEXT[]``; here it is JSON (a list of
    camera ids) so the SAME model runs on dev SQLite and prod Postgres.
  * ``users.password`` keeps its legacy column NAME but the Python attribute is
    ``password_hash`` — it only ever stores a bcrypt hash.
  * ``audit_log`` is upgraded to the tamper-evident hash-chain design (TEXT
    auditRef id + monotonic ``seq`` + prev_hash/row_hash) lifted from the
    dispatch gateway; the legacy columns (officer, action, violation_id, at,
    notes) are preserved so the renderer's audit view still has its fields.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # bcrypt hash ONLY — legacy column name "password" kept for schema parity.
    password_hash: Mapped[str] = mapped_column("password", String(128))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    # admin | supervisor | officer
    role: Mapped[str] = mapped_column(String(24), default="officer")
    # Privilege bool dict: canApprove, canDismiss, canRevise, canManageUsers,
    # canManageCameras, canViewAudit, canExport. ALL authz is server-side and
    # reads this LIVE row (immediate revocation) — never the JWT claims.
    privileges: Mapped[dict] = mapped_column(JSON, default=dict)
    # Soft-delete flag: DELETE /auth/users/{id} sets active=false (preserves
    # audit lineage). An inactive user cannot log in AND any already-issued
    # access token stops working immediately (security.current_user rejects it).
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    keybinds: Mapped[dict] = mapped_column(JSON, default=dict)
    theme: Mapped[str] = mapped_column(String(24), default="dark")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RefreshToken(Base):
    """Rotation + family reuse-detection — lifted from the dispatch gateway."""

    __tablename__ = "refresh_tokens"
    token: Mapped[str] = mapped_column(String(512), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    # The token's own jti claim (diagnostics; the token itself stays the PK).
    jti: Mapped[str] = mapped_column(String(32), default="", index=True)
    # Rotation lineage: set once at login, inherited by every rotated successor.
    # Detecting a revoked token being re-presented revokes the whole family.
    family_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    # The successor token minted when this one was rotated ('' = current leaf).
    replaced_by: Mapped[str] = mapped_column(String(512), default="")
    # When this token was rotated out (refreshed). NULL = never rotated.
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When a revoked token was re-presented = detected compromise. NULL = none.
    reused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Violation(Base):
    __tablename__ = "violations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    speed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plate: Mapped[str] = mapped_column(String(24), default="")
    vehicle: Mapped[str] = mapped_column(String(128), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    # JSON list of camera ids (legacy Postgres TEXT[] — JSON is portable).
    cameras: Mapped[list] = mapped_column(JSON, default=list)
    camera: Mapped[str] = mapped_column(String(64), default="")
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    weather: Mapped[str] = mapped_column(String(64), default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    # Legacy inline review fields (kept for schema parity / initial ingest);
    # violation_reviews is the authoritative review record (LEFT JOIN on read).
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    history: Mapped[list] = mapped_column(JSON, default=list)
    # Evidence object keys/URLs (presigned server-side via storage.py).
    clip_url: Mapped[str] = mapped_column(Text, default="")
    raw_clip_url: Mapped[str] = mapped_column(Text, default="")
    screenshot_url: Mapped[str] = mapped_column(Text, default="")
    # Rack enforcement-gate verdict (citation-lifecycle bridge, see
    # DecisionOutbox below). NULL/unset until the rack sync populates it —
    # nothing writes these two columns yet except dev seed data. `citable`
    # gates whether an approved decision may ever become a citation
    # (gateway_api_contract.md "Camera citations"); `gate_reason` is the
    # human-readable basis (e.g. "gate: citation class, certified basis").
    citable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gate_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default="")


class ViolationReview(Base):
    """The authoritative review record — one row per reviewed violation.
    reviewed_by / reviewed_at are ALWAYS set server-side from the token +
    server clock (client-supplied values are never trusted)."""

    __tablename__ = "violation_reviews"
    violation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("violations.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(24), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    history: Mapped[list] = mapped_column(JSON, default=list)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    location: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="online")
    last_ping: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CameraLane(Base):
    __tablename__ = "camera_lanes"
    camera_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    lane_data: Mapped[dict] = mapped_column(JSON, default=dict)
    calibration_width: Mapped[int] = mapped_column(Integer, default=0)
    calibration_height: Mapped[int] = mapped_column(Integer, default=0)
    background_frame_url: Mapped[str] = mapped_column(Text, default="")
    background_frame_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class AuditLog(Base):
    """Immutable, tamper-evident record of every review/user/camera mutation
    and login. Rows are written SERVER-SIDE only (client-supplied officer/at
    are never trusted). See gateway/audit.py for the hash-chain source of
    truth."""

    __tablename__ = "audit_log"
    # Random display auditRef (e.g. AUD-RAP-3F9A1C) — NOT the chain order.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Monotonic chain position. This — NOT `at` (clock skew / equal timestamps)
    # and NOT the random `id` — is the load-bearing chain ORDER.
    seq: Mapped[int] = mapped_column(
        Integer, autoincrement=True, unique=True, index=True
    )
    # Username of the acting user ('system' for machine actions).
    officer: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    violation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    notes: Mapped[str] = mapped_column(String(512), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    # ---- tamper-evidence hash chain (gateway/audit.py is the source of truth) ----
    # hex sha256/HMAC of the PREVIOUS row's row_hash; GENESIS (64 zeros) for seq==1.
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    # hex sha256/HMAC over the canonical serialization of THIS row + prev_hash.
    row_hash: Mapped[str] = mapped_column(String(64), default="", index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))
    msg: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class NotificationRead(Base):
    """PER-USER read state for a broadcast notification.

    ``notifications.read`` is a single global flag: one reviewer marking a
    notification read hid it from every other reviewer on every desk. Read
    state is a property of (notification, user), so it lives here. The legacy
    column is left in place for older rows/tools but is no longer what the
    API reports.
    """

    __tablename__ = "notification_reads"
    notification_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="operational")
    detail: Mapped[str] = mapped_column(Text, default="")
    uptime: Mapped[str] = mapped_column(String(32), default="")
    latency: Mapped[str] = mapped_column(String(32), default="")
    usage: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class SystemStatus(Base):
    """Latest-row-wins system snapshot (the app reads ORDER BY timestamp DESC
    LIMIT 1). Columns beyond timestamp were never pinned down in the legacy
    schema, so the payload is a JSON blob."""

    __tablename__ = "system_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="ok")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class DecisionOutbox(Base):
    """Transactional outbox — step 1 of the citation-lifecycle bridge (see
    gateway_api_contract.md, "Camera citations — the review->service bridge").

    Semantics (do not weaken these when this table grows a consumer):
      * APPEND-ONLY. A row is written once, by ``routers.violations.patch_review``,
        and never mutated by this codebase. The future push worker only ever
        SETs ``delivered_at``/``attempts``/``last_error`` on an *approved* row —
        it never edits ``payload``.
      * SAME-TRANSACTION-AS-DECISION. The outbox row is added to the SAME
        SQLAlchemy session/commit that writes the ``ViolationReview`` row and
        the ``AuditLog`` row for that review change (see audit.record's own
        stage-don't-commit contract). If the commit fails, NONE of the three
        rows persist — that is what makes the outbox a reliable source for the
        future push worker (no decision is ever "recorded" without its outbox
        entry, and no outbox entry exists without a real recorded decision).
      * ``id`` IS THE BRIDGE EVENT ID. This monotonic autoincrement integer is
        ``sourceEventId`` end-to-end: the push worker's idempotency key into
        the OTHER gateway's ``POST /citations/from-review``, the review
        gateway's own ``/decisions/feed?since=<eventId>`` cursor, and the
        reconciliation join key. Never re-derive or re-mint an event id
        elsewhere.
      * ONE ROW PER TRANSITION. Every actual STATUS change (pending<->approved,
        pending<->dismissed, approved<->dismissed, and back) appends exactly
        one new row — re-deciding a violation multiple times produces multiple
        outbox rows, each independently delivered/reconciled. A note-only or
        pinned-only PATCH is not a decision and writes no row.
      * ``decision`` is "approved" | "dismissed" | "reopened" — "reopened"
        covers any transition BACK to pending from a decided state.
      * ``delivered_at`` stays NULL forever for "dismissed"/"reopened" rows —
        those are provenance/feed-only entries; only an "approved" row is ever
        actually pushed to the dispatch gateway, so only it can be delivered.

    Step 2 (bridge_worker.py) additions — same append-only posture: the
    worker may only ever SET ``delivered_at``/``attempts``/``last_error``/
    ``parked_at``/``next_attempt_at`` on an approved row, never ``payload``.
      * ``parked_at`` NULL = not parked. Set ONLY on a non-retryable delivery
        outcome (422 non_citable / unmapped_offence per the contract) and is
        PERMANENT — a parked row is excluded from the worker's query forever;
        re-delivery is a deliberate manual/ops action, never automatic.
      * ``next_attempt_at`` NULL = eligible now. Set on every retryable
        failure to ``now + backoff(attempts)`` (exponential + jitter, see
        bridge_worker.select_due) so a struggling/duplicate row does not spin
        the worker's poll loop.
    """

    __tablename__ = "decision_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    violation_id: Mapped[str] = mapped_column(String(64), index=True)
    # approved | dismissed | reopened
    decision: Mapped[str] = mapped_column(String(16))
    # Full event snapshot handed to the push worker / decision feed verbatim —
    # see routers.violations for the exact camelCase shape (matches the
    # gateway_api_contract.md POST /citations/from-review body).
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    # NULL = undelivered. Only ever set for "approved" rows, only ever by the
    # future push worker (never by this router).
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    # NULL = not parked. Set once, permanently, on a non-retryable (422)
    # delivery outcome. Parked rows are excluded from the worker's undelivered
    # query and surface separately as "quarantined" on /system/status.
    parked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # NULL = due now. Set on a retryable failure to the next eligible retry
    # time (per-row exponential backoff + jitter); the worker's query only
    # selects rows where this is NULL or already in the past.
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
