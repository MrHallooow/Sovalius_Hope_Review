"""Evidence read-side: CASE-BOUND presigned GETs + the local blob proxy.

GET /violations/{id}/evidence  -> { ok, clipUrl, rawUrl, screenshotUrl,
                                    tracksUrl }   (bearer auth)
GET /evidence/blob/{token}     (LOCAL backend only; NO bearer auth — the
                                signed, expiring token IS the capability,
                                mirroring the dispatch gateway's
                                unauthenticated presigned blob route)

SECURITY CONTRACT — why the caller no longer supplies keys.
The retired ``GET /evidence/urls?clipUrl=&screenshotUrl=&rawClipUrl=`` minted
a capability for ANY object key an authenticated caller typed, with no link
to a case and no audit trail: one reviewer's token could enumerate evidence
belonging to cases they were never shown. Evidence is now addressed ONLY by
violation id; the keys come from that violation's own stored columns, and
every issuance writes an ``evidence_accessed`` audit row naming the reviewer,
the case, and which capabilities were handed out (never the signed URLs
themselves — those are bearer secrets).

Key extraction keeps the old electron/main.js extractS3Key semantics: parse
the stored value as a URL and take the pathname minus its leading slash;
anything unparseable yields null and the response field is null — never an
error (a missing key simply leaves that URL null). The response keys keep
main.js's exact names: the signed *raw clip* comes back as ``rawUrl``.

Documented divergence from main.js: a bare S3-style key (no scheme, e.g.
``violations/VIO-2026-00147/clip.mp4``) is accepted as the key itself.
main.js returned null there only because ``new URL()`` throws on relative
input; local dev rows store raw keys, so refusing them would break the local
evidence flow.

CPU-erasure Phase 3 (review side): the rack ships a ``tracks.json`` sidecar as
a SIBLING of ``clip_raw.mp4`` in the same storage folder. ``tracksUrl`` is
derived from the violation's raw-clip key by swapping the filename for
``tracks.json`` and presigned through the exact same store — no existence
check, same 404-on-fetch semantics as every other evidence field, so old
evidence with no sidecar degrades to "no overlay data" rather than an error.
"""

from __future__ import annotations

import mimetypes
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import audit, models
from ..db import get_db
from ..security import current_user
from ..storage import EvidenceStore, verify_blob_token

router = APIRouter(tags=["Evidence"])


def _store(request: Request) -> EvidenceStore:
    return request.app.state.evidence_store


def extract_key(url: str | None) -> str | None:
    """Return a safe object key from a stored URL or a legacy bare key."""
    if not url:
        return None
    value = str(url).strip()
    if not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme:
        key = parts.path.lstrip("/")
        return key or None
    if value.startswith("/"):
        return None
    return value


def sibling_key(key: str | None, filename: str) -> str | None:
    if not key:
        return None
    index = key.rfind("/")
    return (key[: index + 1] if index >= 0 else "") + filename


def _presign(store: EvidenceStore, raw: str | None) -> str | None:
    key = extract_key(raw)
    return store.presign_get(key) if key else None


def _urls_for(violation: models.Violation, store: EvidenceStore) -> dict:
    raw_key = extract_key(violation.raw_clip_url)
    tracks_key = sibling_key(raw_key, "tracks.json")
    return {
        "ok": True,
        "clipUrl": _presign(store, violation.clip_url),
        "rawUrl": _presign(store, violation.raw_clip_url),
        "screenshotUrl": _presign(store, violation.screenshot_url),
        "tracksUrl": store.presign_get(tracks_key) if tracks_key else None,
    }


@router.get("/violations/{violation_id}/evidence")
def violation_evidence_urls(
    violation_id: str,
    request: Request,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Issue auditable, short-lived evidence links for one known case."""
    violation = db.get(models.Violation, violation_id)
    if violation is None:
        raise HTTPException(status_code=404, detail="Unknown violation")

    urls = _urls_for(violation, _store(request))
    audit.record(
        db,
        officer=user.username,
        action="evidence_accessed",
        violation_id=violation_id,
        detail={
            # Which capabilities were handed out, without logging the signed
            # URLs themselves (they are bearer capabilities).
            "issued": sorted(k for k in ("clipUrl", "rawUrl", "screenshotUrl", "tracksUrl") if urls.get(k)),
        },
    )
    db.commit()
    return urls


@router.get("/evidence/blob/{token}")
def get_blob(token: str, request: Request) -> Response:
    """Serve a verified local capability URL.

    The signed token is intentionally sufficient after it has been issued to
    an authenticated reviewer.  S3 deployments serve their own presigned
    links and never enter this route.
    """
    store = _store(request)
    if not getattr(store, "is_proxy", False):
        raise HTTPException(status_code=404, detail="blob proxy not available")
    key = verify_blob_token(token)
    if key is None:
        raise HTTPException(status_code=404, detail="unknown or expired evidence token")

    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    path_for_read = getattr(store, "path_for_read", None)
    if callable(path_for_read):
        path = path_for_read(key)
        if path is not None:
            return FileResponse(path, media_type=media_type)

    data = store.read(key)
    if data is None:
        raise HTTPException(status_code=404, detail="evidence object not found")
    return Response(content=data, media_type=media_type)
