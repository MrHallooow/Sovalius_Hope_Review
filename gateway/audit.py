"""Tamper-evidence layer for the review audit_log.

The audit_log records every review decision, user-admin change, camera change
and login. For evidentiary value it must be *tamper-evident*: any mutation,
deletion, reordering, or insertion of a row must be detectable after the fact.
Lifted from the proven sovalius-dispatch gateway hash chain, with review
action codes.

This module is the single source of truth for:
  * the per-row hash chain (seq + prev_hash + row_hash),
  * the canonical serialization + hash function,
  * the central ``record()`` append helper (stages, does NOT commit),
  * the append-only ``before_flush`` guard,
  * ``verify_chain()`` (detect mutation / deletion / reordering).

Layered immutability model:
  1. app-level before_flush guard   -> prevents accidental ORM mutation
  2. hash chain                     -> DETECTS tampering (any backend)
  3. keyed HMAC (GWREV_AUDIT_HMAC)  -> makes forgery infeasible without the
                                       gateway secret
  4. Postgres GRANT (deploy step)   -> REVOKE UPDATE/DELETE on audit_log from
                                       the gateway role is the real backstop

The guard stops accidents in app code; it does NOT stop a DBA with raw SQL —
that is exactly what the hash chain detects and what keyed HMAC + DB grants
prevent. Do not oversell the guard.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .util import iso, short_id

# Bounded retries when two concurrent appenders race the same chain seq (see
# record()). Far above any real contention; a backstop against a genuine
# constraint bug spinning forever.
_MAX_SEQ_RETRIES = 8

# Genesis sentinel for the very first row's prev_hash (seq == 1). 64 hex zeros
# so it is the same width as a real sha256 digest and obviously "the start".
GENESIS = "0" * 64

# action -> auditRef prefix (review action codes).
_PREFIX = {
    "review_approved": "AUD-RAP",
    "review_dismissed": "AUD-RDI",
    "review_reopened": "AUD-RRE",  # decided -> pending (a canRevise action)
    "review_notes": "AUD-RNT",  # notes-only edit of a review
    "violation_viewed": "AUD-RVW",
    "evidence_accessed": "AUD-EVD",  # short-lived evidence links issued for a case
    "pinned": "AUD-RPN",
    "user_admin": "AUD-USR",
    "camera_change": "AUD-CAM",
    "service_change": "AUD-SVC",
    "login": "AUD-LOG",
}

# The canonical, FIXED field set hashed for each row. Never hash vars(row) —
# the set must be explicit and stable so the hash is reproducible across
# code/schema changes and across SQLite (naive datetimes) vs Postgres
# (tz-aware).
_FIELDS = ("seq", "id", "officer", "action", "violation_id", "notes", "detail", "at")


# ---------------------------------------------------------------------------
# Canonicalization + hash (dependency-free so a future backfill migration can
# import them and hash IDENTICALLY to the app)
# ---------------------------------------------------------------------------
def _canonical(row_fields: dict) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, str() fallback for
    anything non-JSON (e.g. a stray datetime). Recurses into the detail dict
    via sort_keys so nested ordering can't change the hash."""
    return json.dumps(
        row_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def fixed_fields(*, seq, id, officer, action, violation_id, notes, detail, at) -> dict:
    """Assemble the FIXED canonical field dict for one row.

    ``at`` is serialized through util.iso() (ISO-8601 UTC) so the SAME bytes
    hash whether the backend stored a naive (SQLite) or tz-aware (Postgres)
    datetime — this is the single biggest verify trap. detail defaults to {}
    so a NULL/absent detail hashes identically to an empty dict.
    """
    return {
        "seq": seq,
        "id": id,
        "officer": officer or "",
        "action": action or "",
        "violation_id": violation_id or "",
        "notes": notes or "",
        "detail": detail or {},
        "at": iso(at),
    }


def _chain_key() -> bytes:
    """HMAC key for keyed-chain mode, read the same way security._secret()
    reads the on-disk gateway secret. Imported lazily to avoid a circular
    import at module load and so plain (dev/test) mode never touches the
    secret file."""
    from .security import _secret

    return _secret()


def compute_row_hash(prev_hash: str, fields: dict) -> str:
    """Hash THIS row's canonical content chained onto prev_hash.

    Plain mode (dev/test default, deterministic without a secret): sha256.
    Keyed mode (settings.audit_hmac, recommended for prod): HMAC-SHA256 under
    the gateway secret, so an attacker who can WRITE the DB still cannot forge
    a valid chain without the key — defense-in-depth beyond detect-only sha256.
    """
    payload = {"prev_hash": prev_hash, **fields}
    data = _canonical(payload)
    if settings.audit_hmac:
        return hmac.new(_chain_key(), data, hashlib.sha256).hexdigest()
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Tail read (concurrency-safe prev_hash/seq) + central append helper
# ---------------------------------------------------------------------------
def _tail(db: Session):
    """Return the current chain tail (highest seq) row, or None for an empty
    chain.

    CONCURRENCY: the chain is a linked list, so two concurrent appends must not
    read the same tail (that forks the chain into two rows sharing one
    prev_hash). On Postgres we take a row lock (SELECT ... FOR UPDATE) so the
    second appender blocks until the first commits. On SQLite the connection is
    serialized (single writer) so a plain ORDER BY seq DESC LIMIT 1 is safe.
    """
    q = db.query(models.AuditLog).order_by(models.AuditLog.seq.desc())
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.with_for_update()
    return q.first()


def record(
    db: Session,
    *,
    officer: str,
    action: str,
    violation_id: str = "",
    notes: str = "",
    detail: dict | None = None,
) -> str:
    """Append one tamper-evident audit row and return its id (auditRef).

    Does NOT commit — the caller's existing db.commit() commits the audit row
    in the SAME transaction as the action it records. Committing here would
    split the audit row into its own txn and could orphan it if the action
    later fails.
    """
    audit_ref = short_id(_PREFIX.get(action, "AUD"))
    at = models._utcnow()

    # Concurrency: two requests on SEPARATE connections (uvicorn's threadpool,
    # or a multi-worker deploy) can read the same chain tail and try to append
    # the same seq, colliding on the audit_log.seq UNIQUE index. _tail() takes
    # a row lock (FOR UPDATE) to serialize this on Postgres, but SQLite has no
    # such lock — so we retry on the IntegrityError: re-read the tail (now
    # seeing the winner's committed row), re-chain off it, and re-insert. The
    # audit row is staged inside a SAVEPOINT so a lost race discards only the
    # failed insert, never the action being recorded.
    last_exc: IntegrityError | None = None
    for _ in range(_MAX_SEQ_RETRIES):
        tail = _tail(db)
        if tail is None:
            seq = 1
            prev_hash = GENESIS
        else:
            seq = (tail.seq or 0) + 1
            prev_hash = tail.row_hash

        fields = fixed_fields(
            seq=seq,
            id=audit_ref,
            officer=officer,
            action=action,
            violation_id=violation_id,
            notes=notes,
            detail=detail,
            at=at,
        )
        row_hash = compute_row_hash(prev_hash, fields)
        try:
            # SAVEPOINT so a lost seq race rolls back just this insert, leaving
            # the caller's outer transaction intact. Flush inside it so the
            # UNIQUE collision raises here (also makes the row visible to a
            # subsequent _tail() within the same uncommitted transaction).
            with db.begin_nested():
                db.add(
                    models.AuditLog(
                        id=audit_ref,
                        seq=seq,
                        officer=officer,
                        action=action,
                        violation_id=violation_id,
                        notes=notes,
                        detail=detail or {},
                        at=at,
                        prev_hash=prev_hash,
                        row_hash=row_hash,
                    )
                )
                db.flush()
            return audit_ref
        except IntegrityError as exc:
            # Another appender won this seq; drop the stale tail and re-chain.
            last_exc = exc
            db.expire_all()
    # Exhausted retries — surface the real integrity error rather than masking it.
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Append-only discipline (app-level guard; not a substitute for DB grants)
# ---------------------------------------------------------------------------
def _row_fields_of(row: models.AuditLog) -> dict:
    return fixed_fields(
        seq=row.seq,
        id=row.id,
        officer=row.officer,
        action=row.action,
        violation_id=row.violation_id,
        notes=row.notes,
        detail=row.detail,
        at=row.at,
    )


def _before_flush(session: Session, flush_context, instances) -> None:
    """Hard-fail any attempt to UPDATE or DELETE an AuditLog via the ORM.

    Newly-added rows (session.new) are allowed — that is the append path.
    Detail dicts are mutable JSON; an in-place change marks the parent dirty,
    so catching session.dirty also catches ``row.detail['x'] = ...`` tampering.
    """
    for obj in session.dirty:
        if isinstance(obj, models.AuditLog) and session.is_modified(
            obj, include_collections=False
        ):
            raise RuntimeError("audit_log is append-only: UPDATE is not permitted")
    for obj in session.deleted:
        if isinstance(obj, models.AuditLog):
            raise RuntimeError("audit_log is append-only: DELETE is not permitted")


def install_guards() -> None:
    """Register the append-only before_flush guard once. Idempotent."""
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def verify_chain(db: Session, start_seq: int = 1, limit: int | None = None) -> dict:
    """Single O(n) pass over the chain ordered by seq ASC.

    Detects:
      * mutation   -> recomputed row_hash != stored row_hash
      * deletion   -> a gap in the contiguous seq sequence
      * reordering / insertion -> a row's prev_hash != the prior row's row_hash

    Returns {ok, checked, head_seq, head_hash, first_broken_seq, reason}.
    """
    q = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.seq >= start_seq)
        .order_by(models.AuditLog.seq.asc())
    )
    if limit is not None:
        q = q.limit(limit)
    rows = q.all()

    checked = 0
    head_seq = None
    head_hash = None
    expected_prev = GENESIS if start_seq <= 1 else None
    expected_seq = start_seq

    for row in rows:
        # Contiguity (gap == deletion). For a partial verify (start_seq > 1)
        # the first row anchors expected_seq, so we only enforce contiguity
        # onward.
        if row.seq != expected_seq:
            return {
                "ok": False,
                "checked": checked,
                "head_seq": head_seq,
                "head_hash": head_hash,
                "first_broken_seq": row.seq,
                "reason": (
                    f"seq gap: expected {expected_seq}, found {row.seq} "
                    "(row deleted or chain truncated)"
                ),
            }

        # prev_hash linkage (reordering / insertion).
        if expected_prev is not None and row.prev_hash != expected_prev:
            return {
                "ok": False,
                "checked": checked,
                "head_seq": head_seq,
                "head_hash": head_hash,
                "first_broken_seq": row.seq,
                "reason": "prev_hash mismatch (chain reordered, spliced, or row inserted)",
            }

        # Row integrity (mutation).
        recomputed = compute_row_hash(row.prev_hash, _row_fields_of(row))
        if recomputed != row.row_hash:
            return {
                "ok": False,
                "checked": checked,
                "head_seq": head_seq,
                "head_hash": head_hash,
                "first_broken_seq": row.seq,
                "reason": "row_hash mismatch (row content was mutated)",
            }

        checked += 1
        head_seq = row.seq
        head_hash = row.row_hash
        expected_prev = row.row_hash
        expected_seq = row.seq + 1

    return {
        "ok": True,
        "checked": checked,
        "head_seq": head_seq,
        "head_hash": head_hash,
        "first_broken_seq": None,
        "reason": "ok",
    }


def head(db: Session) -> dict:
    """Current chain head (for external notarization) + total row count."""
    tail = _tail(db)
    count = db.query(models.AuditLog).count()
    return {
        "seq": tail.seq if tail else 0,
        "hash": tail.row_hash if tail else GENESIS,
        "count": count,
    }
