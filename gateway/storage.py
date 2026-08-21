"""Evidence object-store adapter seam.

One Protocol, two implementations selected purely by ``settings.evidence_store``:

  * ``LocalDiskStore`` (default, zero infra) — the dev/test behaviour: bytes
    live under ``settings.evidence_dir`` and "presigned" GET URLs point at the
    gateway's own ``/evidence/blob/{token}`` endpoint. The dispatch gateway's
    dev presign relied on the key being unguessable (random ``ev-XXXX`` ids);
    review evidence keys are GUESSABLE (``violations/<id>/clip.mp4``), so here
    the capability is a real signature: an HMAC-SHA256 token under the gateway
    secret embedding {key, exp}, time-limited like a genuine S3 presign
    (``mint_blob_token`` / ``verify_blob_token``). ``head()`` reads the file
    off disk and recomputes its sha256, so verification is genuine with no S3.

  * ``S3Store`` (boto3 against MinIO or AWS — a config-only switch). Mints
    genuine presigned GET/PUT URLs so the app talks to object storage directly
    (the gateway never proxies the bytes). boto3 is imported LAZILY inside
    ``S3Store`` so the default local backend (and the test suite) need no
    boto3 and make NO network calls.

The review app's evidence flow today is read-side (GET /evidence/urls returns
presigned GETs for clip/screenshot/raw-clip). ``presign_put`` is designed in
for the future ingest path; the corresponding endpoint may 501 until wired.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from .config import Settings


# ---------------------------------------------------------------------------
# Value objects returned by the adapter
# ---------------------------------------------------------------------------
@dataclass
class PresignResult:
    """A presigned (or local proxy) PUT target the client uploads bytes to.

    ``headers`` are the EXACT headers the client MUST echo on its PUT — for S3
    they include the checksum header that makes S3/MinIO reject a tampered
    body.
    """

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass
class ObjectInfo:
    """What the store knows about a stored object after upload (HEAD)."""

    size: int
    etag: str = ""
    sha256: str = ""  # hex; recomputed (local) or from object checksum/metadata (S3)
    content_type: str = ""


@runtime_checkable
class EvidenceStore(Protocol):
    # True only for the local backend; routers use it to decide whether the
    # gateway should serve the byte-proxy endpoint at all.
    is_proxy: bool

    def presign_get(self, key: str) -> str:
        """A time-limited (S3) or capability-by-unguessable-key (local) GET URL."""
        ...

    def presign_put(
        self, key: str, *, content_type: str, sha256: str, max_bytes: int
    ) -> PresignResult: ...

    def head(self, key: str) -> ObjectInfo | None: ...

    def open_for_write(self, key: str, data: bytes) -> int:
        """Local-only: persist bytes for the proxy PUT. Returns bytes written."""
        ...

    def read(self, key: str) -> bytes | None:
        """Local-only: bytes for the GET blob proxy. S3 deployments serve GETs
        straight from object storage via the presigned URL."""
        ...

    def delete(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hex_to_b64(sha256_hex: str) -> str:
    """base64 of the raw 32 sha256 BYTES — what S3/MinIO's ChecksumSHA256 wants.

    Passing the hex string here makes the store reject every upload, so this
    conversion is load-bearing.
    """
    return base64.b64encode(bytes.fromhex(sha256_hex)).decode("ascii")


def _b64_to_hex(value: str) -> str:
    """Best-effort decode of an S3 ChecksumSHA256 (base64) back to hex.
    Returns '' if not decodable."""
    try:
        return binascii.hexlify(base64.b64decode(value, validate=True)).decode("ascii")
    except (binascii.Error, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Local "presign": signed, expiring blob tokens (LocalDiskStore GET URLs)
# ---------------------------------------------------------------------------
# Why not the dispatch gateway's bare-key capability? Its keys carried
# short_id() randomness, so the key itself was unguessable. Review evidence
# keys are DERIVED from violation ids (violations/VIO-2026-00147/clip.mp4) —
# trivially guessable — so the local GET route must not accept raw keys.
# Instead presign_get mints an HMAC-SHA256 token under the gateway secret
# (same key material security._secret() / audit._chain_key() use) embedding
# the object key and an absolute expiry, mirroring genuine S3 presign
# semantics: time-limited, unforgeable, no bearer auth on the blob route.

def _blob_sig(payload: bytes) -> str:
    # Lazy import (like audit._chain_key) so module load never touches the
    # secret file and there is no circular import at import time.
    from .security import _secret

    digest = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def mint_blob_token(key: str, ttl_sec: int) -> str:
    """Mint ``<b64url(payload)>.<b64url(hmac)>`` for one object key.

    URL-path-safe by construction (base64url alphabet + one dot), so the token
    rides in ``/evidence/blob/{token}`` as a single path segment.
    """
    payload = json.dumps(
        {"exp": int(time.time()) + int(ttl_sec), "key": key},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    p64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    return f"{p64}.{_blob_sig(payload)}"


def verify_blob_token(token: str) -> str | None:
    """Return the object key for a valid, unexpired token; None otherwise.

    Signature is checked BEFORE the payload is trusted (constant-time compare),
    so a forged/tampered token never influences behaviour beyond the None.
    """
    p64, _, sig = token.partition(".")
    if not p64 or not sig:
        return None
    try:
        payload = base64.urlsafe_b64decode(p64 + "=" * (-len(p64) % 4))
    except (binascii.Error, ValueError):
        return None
    if not hmac.compare_digest(sig, _blob_sig(payload)):
        return None
    try:
        obj = json.loads(payload)
    except ValueError:
        return None
    key = obj.get("key")
    exp = obj.get("exp")
    if not isinstance(key, str) or not key:
        return None
    try:
        if int(exp) < time.time():
            return None
    except (TypeError, ValueError):
        return None
    return key


# ---------------------------------------------------------------------------
# LocalDiskStore — default, zero infra
# ---------------------------------------------------------------------------
class LocalDiskStore:
    is_proxy = True

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _path(self, key: str):
        # Keys are namespaced (violations/<id>/clip.mp4); flatten the
        # separators so the proxy never escapes evidence_dir and we get one
        # file per key.
        safe = key.replace("/", "__").replace("\\", "__")
        return self._settings.evidence_dir / safe

    def presign_get(self, key: str) -> str:
        # Signed local token URL (see mint_blob_token above): review keys are
        # guessable, so unlike the dispatch dev presign the capability is a
        # real HMAC signature + expiry, not the key itself. Absolute
        # (public_base_url) so the Electron app can resolve it without
        # prepending its API base; relative when unset (test/same-origin).
        base = (self._settings.public_base_url or "").rstrip("/")
        token = mint_blob_token(key, self._settings.evidence_url_ttl_sec)
        return f"{base}/evidence/blob/{token}"

    def presign_put(
        self, key: str, *, content_type: str, sha256: str, max_bytes: int
    ) -> PresignResult:
        base = (self._settings.public_base_url or "").rstrip("/")
        url = f"{base}/evidence/blob/{key}"
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._settings.evidence_url_ttl_sec
        )
        return PresignResult(
            url=url,
            headers={"content-type": content_type, "x-amz-meta-sha256": sha256},
            expires_at=expires_at,
        )

    def open_for_write(self, key: str, data: bytes) -> int:
        self._settings.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._path(key).write_bytes(data)
        return len(data)

    def read(self, key: str) -> bytes | None:
        """Local-only: the bytes behind a verified blob token (GET proxy).
        Dev-scale objects, so an in-memory read keeps the route trivial."""
        p = self._path(key)
        if not p.is_file():
            return None
        return p.read_bytes()

    def path_for_read(self, key: str):
        """Return an object path for ranged HTTP delivery.

        This avoids copying a whole evidence clip into gateway memory before a
        reviewer can seek through it.
        """
        p = self._path(key)
        return p if p.is_file() else None

    def head(self, key: str) -> ObjectInfo | None:
        p = self._path(key)
        if not p.is_file():
            return None
        data = p.read_bytes()
        return ObjectInfo(
            size=len(data),
            etag=hashlib.md5(data).hexdigest(),  # noqa: S324 — etag only, not security
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.is_file():
            p.unlink()


# ---------------------------------------------------------------------------
# S3Store — boto3 against MinIO or AWS (config-only switch; lazy import)
# ---------------------------------------------------------------------------
class S3Store:
    is_proxy = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bucket = settings.s3_bucket
        self._client = None  # lazily built so import-time needs no boto3

    def _get_client(self):
        if self._client is None:
            # LAZY import: boto3 is an optional dep; only the S3 backend needs it.
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self._settings.s3_endpoint_url or None,
                aws_access_key_id=self._settings.s3_access_key or None,
                aws_secret_access_key=self._settings.s3_secret_key or None,
                region_name=self._settings.s3_region,
                # Path-style + s3v4 is what MinIO needs; harmless for AWS.
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                ),
            )
        return self._client

    def presign_get(self, key: str) -> str:
        client = self._get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._settings.evidence_url_ttl_sec,
        )

    def presign_put(
        self, key: str, *, content_type: str, sha256: str, max_bytes: int
    ) -> PresignResult:
        client = self._get_client()
        b64 = _hex_to_b64(sha256)
        ttl = self._settings.evidence_url_ttl_sec
        url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": content_type,
                # Integrity enforced at PUT time: S3/MinIO reject the body if
                # its checksum differs from this presigned ChecksumSHA256.
                "ChecksumSHA256": b64,
                "Metadata": {"sha256": sha256},
            },
            ExpiresIn=ttl,
            HttpMethod="PUT",
        )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        return PresignResult(
            url=url,
            headers={
                "content-type": content_type,
                # The client MUST echo the SAME base64 checksum or the
                # signature (and integrity check) fail.
                "x-amz-checksum-sha256": b64,
                "x-amz-meta-sha256": sha256,
            },
            expires_at=expires_at,
        )

    def open_for_write(self, key: str, data: bytes) -> int:  # pragma: no cover
        # S3 deployments never proxy bytes through the gateway; the client PUTs
        # straight to object storage. Present only to satisfy the Protocol.
        raise RuntimeError("S3Store does not proxy uploads; PUT to the presigned URL")

    def read(self, key: str) -> bytes | None:  # pragma: no cover
        # Same rationale: GETs go straight to object storage via the presigned
        # URL; the gateway never proxies S3 bytes.
        raise RuntimeError("S3Store does not proxy downloads; GET the presigned URL")

    def head(self, key: str) -> ObjectInfo | None:
        client = self._get_client()
        try:
            resp = client.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            return None
        meta = resp.get("Metadata") or {}
        checksum_b64 = resp.get("ChecksumSHA256") or ""
        sha_hex = _b64_to_hex(checksum_b64) if checksum_b64 else (meta.get("sha256") or "")
        return ObjectInfo(
            size=int(resp.get("ContentLength") or 0),
            etag=str(resp.get("ETag") or "").strip('"'),
            sha256=sha_hex,
            content_type=str(resp.get("ContentType") or ""),
        )

    def delete(self, key: str) -> None:  # pragma: no cover
        client = self._get_client()
        client.delete_object(Bucket=self._bucket, Key=key)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def build_store(settings: Settings) -> EvidenceStore:
    """Pick the evidence backend from config. 'local' (default) keeps the
    zero-infra behaviour; 's3' selects the lazy-boto3 store."""
    if (settings.evidence_store or "local").lower() == "s3":
        return S3Store(settings)
    return LocalDiskStore(settings)
