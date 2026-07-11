"""Evidence read-side: presigned GET URLs + the local blob proxy.

GET /evidence/urls?clipUrl=&screenshotUrl=&rawClipUrl=
        -> { ok, clipUrl, rawUrl, screenshotUrl, tracksUrl }   (bearer auth;
        nulls, not errors)
GET /evidence/blob/{token}                          (LOCAL backend only; NO bearer
        auth — the signed, expiring token IS the capability, mirroring the
        dispatch gateway's unauthenticated presigned blob route)

Key extraction mirrors electron/main.js extractS3Key (main.js:39-47 /
evidence:get-urls at main.js:502-546): parse the stored value as a URL and take
the pathname minus its leading slash; anything unparseable yields null and the
response field is null — never an error (matches current app behaviour where a
missing key simply leaves that URL null). The response keys keep main.js's
exact names: the signed *raw clip* comes back as ``rawUrl``.

Documented divergence from main.js: a bare S3-style key (no scheme, e.g.
``violations/VIO-2026-00147/clip.mp4``) is accepted as the key itself. main.js
returned null there only because ``new URL()`` throws on relative input; local
dev rows store raw keys, so refusing them would break the local evidence flow.

CPU-erasure Phase 3 (review side): the rack ships a ``tracks.json`` sidecar as
a SIBLING of ``clip_raw.mp4`` in the same storage folder (the uploader already
ships any ``.json`` file alongside the clips). ``tracksUrl`` is derived from
``rawClipUrl``'s key by swapping the filename for ``tracks.json`` and presigned
through the exact same store — no existence check, same 404-on-fetch semantics
as every other evidence field.
"""

from __future__ import annotations

import mimetypes
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import models
from ..security import current_user
from ..storage import EvidenceStore, verify_blob_token

router = APIRouter(tags=["Evidence"])


def _store(request: Request) -> EvidenceStore:
    """The process-wide evidence store built once in create_app()."""
    return request.app.state.evidence_store


def extract_key(url: str | None) -> str | None:
    """S3-style object key from a stored URL/key field (main.js parity).

    * absolute URL (http/https/s3/...) -> pathname minus the leading slash,
      kept percent-encoded exactly like JS ``new URL().pathname`` (main.js
      never decoded it either);
    * bare relative key               -> itself (documented divergence above);
    * empty / unparseable / rooted    -> None (caller emits null, not an error).
    """
    if not url:
        return None
    s = str(url).strip()
    if not s:
        return None
    try:
        parts = urlsplit(s)
    except ValueError:
        # e.g. malformed IPv6 brackets — main.js's new URL() throws -> null.
        return None
    if parts.scheme:
        key = parts.path.lstrip("/")
        return key or None
    if s.startswith("/"):
        # main.js: new URL("/x") throws (no base) -> null. Same here.
        return None
    return s


def sibling_key(key: str | None, filename: str) -> str | None:
    """Same "folder" as `key`, but with the basename replaced by `filename`.

    Used to locate ``tracks.json`` next to ``clip_raw.mp4`` without any extra
    metadata — the rack and the uploader both key evidence off the clip's
    storage folder, so the sidecar's key is derived, never stored.
    """
    if not key:
        return None
    idx = key.rfind("/")
    folder = key[: idx + 1] if idx >= 0 else ""
    return folder + filename


@router.get("/evidence/urls")
def evidence_urls(
    request: Request,
    clipUrl: str | None = None,
    screenshotUrl: str | None = None,
    rawClipUrl: str | None = None,
    user: models.User = Depends(current_user),
) -> dict:
    """Presigned GETs for the stored evidence fields of a violation, plus the
    derived ``tracks.json`` sidecar for the raw clip.

    No existence check before presigning — genuine S3 presign semantics (and
    main.js parity): a URL for a never-uploaded object simply 404s when
    fetched. Unknown/missing keys -> null fields, never an error. This is how
    old evidence (no tracks.json ever uploaded) degrades gracefully: the
    review app gets a mintable-but-404ing tracksUrl and treats that as
    "no overlay data", not a hard error.
    """
    store = _store(request)

    def _presign(raw: str | None) -> str | None:
        key = extract_key(raw)
        return store.presign_get(key) if key else None

    raw_key = extract_key(rawClipUrl)
    tracks_key = sibling_key(raw_key, "tracks.json")

    return {
        "ok": True,
        "clipUrl": _presign(clipUrl),
        "rawUrl": _presign(rawClipUrl),  # main.js response name for the raw clip
        "screenshotUrl": _presign(screenshotUrl),
        "tracksUrl": store.presign_get(tracks_key) if tracks_key else None,
    }


@router.get("/evidence/blob/{token}")
def get_blob(token: str, request: Request) -> Response:
    """Serve local evidence bytes for a verified presigned token.

    Deliberately NO bearer auth: the HMAC-signed, expiring token is the
    capability, exactly like a real S3 presigned URL (and like the dispatch
    gateway's blob route). Everything invalid is a uniform 404 — expired,
    forged and never-existed tokens are indistinguishable to a prober.
    """
    store = _store(request)
    if not getattr(store, "is_proxy", False):
        # S3 deployments never proxy bytes through the gateway.
        raise HTTPException(status_code=404, detail="blob proxy not available")
    key = verify_blob_token(token)
    if key is None:
        raise HTTPException(status_code=404, detail="unknown or expired evidence token")
    data = store.read(key)
    if data is None:
        raise HTTPException(status_code=404, detail="evidence object not found")
    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(content=data, media_type=media_type)
