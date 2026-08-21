"""Cameras + lane calibration.

GET   /cameras                  (bearer auth)            — main.js db:get-cameras
GET   /camera-lanes             (bearer auth)            — main.js db:get-all-camera-lanes
PATCH /cameras/{id}             (canManageCameras+audit) — main.js db:update-camera
GET   /cameras/{name}/lanes     (bearer auth)            — main.js db:get-camera-lanes
PUT   /cameras/{name}/lanes     (canManageCameras+audit) — main.js db:save-camera-lanes

Server-side hardening vs the legacy IPC handlers:
  * PATCH allowlists mutable columns (location, status) — the legacy handler
    interpolated ARBITRARY client-supplied keys into `SET "<k>" = ...`;
  * both mutations require the canManageCameras privilege read off the LIVE
    user row and append a tamper-evident ``camera_change`` audit row in the
    SAME transaction (audit.record stages; the router commits).

GET lanes mirrors db:get-camera-lanes: no row -> {ok, data: null} (not 404),
and when background_frame_url is set the response carries a presigned GET
minted by the active store (signed local token URL in dev, genuine S3 presign
in prod). Presign failure degrades to null exactly like main.js's try/catch.

PUT lanes mirrors db:save-camera-lanes' UPSERT: lane_data + calibration only —
background_frame_url/_at are deliberately NOT client-writable (they belong to
the ingest pipeline), same as the legacy ON CONFLICT update list.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request
from sqlalchemy.orm import Session

from .. import audit, models
from ..db import get_db
from ..schemas import CameraPatch, LanesPut
from ..security import current_user, require_privilege
from ..util import iso
from .evidence import _store, extract_key

logger = logging.getLogger("revgw.cameras")

router = APIRouter(tags=["Cameras"])

_manage_gate = require_privilege("canManageCameras")


def _camera_json(c: models.Camera) -> dict:
    return {
        "id": c.id,
        "location": c.location,
        "status": c.status,
        "lastPing": iso(c.last_ping),
    }


def _lanes_json(row: models.CameraLane, presigned: str | None) -> dict:
    return {
        "cameraName": row.camera_name,
        "laneData": row.lane_data or {},
        "calibrationWidth": row.calibration_width or 0,
        "calibrationHeight": row.calibration_height or 0,
        "backgroundFrameUrl": row.background_frame_url or None,
        "backgroundFrameAt": iso(row.background_frame_at),
        "backgroundFramePresigned": presigned,
        "updatedAt": iso(row.updated_at),
    }


@router.get("/cameras")
def list_cameras(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.query(models.Camera).order_by(models.Camera.id.asc()).all()
    return {"items": [_camera_json(c) for c in rows]}


@router.get("/camera-lanes")
def list_all_camera_lanes(
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Every lane-calibration row — backs main.js db:get-all-camera-lanes.

    Rows keep the legacy SNAKE_CASE column names (camera_name / lane_data /
    calibration_width / calibration_height / updated_at) because the renderer's
    LaneConfigTab reads them verbatim off the IPC response; ordered by
    camera_name like the legacy ``ORDER BY camera_name``. No presign here —
    the per-camera GET /cameras/{name}/lanes carries the background frame.
    """
    rows = (
        db.query(models.CameraLane)
        .order_by(models.CameraLane.camera_name.asc())
        .all()
    )
    return {
        "ok": True,
        "rows": [
            {
                "camera_name": r.camera_name,
                "lane_data": r.lane_data or {},
                "calibration_width": r.calibration_width or 0,
                "calibration_height": r.calibration_height or 0,
                "updated_at": iso(r.updated_at),
            }
            for r in rows
        ],
    }


@router.patch("/cameras/{camera_id}")
def update_camera(
    camera_id: str,
    body: CameraPatch,
    user: models.User = Depends(_manage_gate),
    db: Session = Depends(get_db),
) -> dict:
    cam = db.get(models.Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="unknown camera")

    changes: dict[str, dict] = {}
    if body.location is not None:
        changes["location"] = {"from": cam.location, "to": body.location}
        cam.location = body.location
    if body.status is not None:
        changes["status"] = {"from": cam.status, "to": body.status}
        cam.status = body.status
    if not changes:
        # Legacy parity: db:update-camera answered "No valid fields".
        raise HTTPException(status_code=400, detail="no updatable fields provided")

    # Tamper-evident record of WHO changed WHAT, committed atomically with the
    # camera row (record() stages; this commit persists both).
    audit.record(
        db,
        officer=user.username,
        action="camera_change",
        notes=f"camera {camera_id} updated",
        detail={"cameraId": camera_id, "changes": changes},
    )
    db.commit()
    return {"ok": True, "camera": _camera_json(cam)}


@router.get("/cameras/{camera_name}/lanes")
def get_camera_lanes(
    camera_name: str,
    request: Request,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(models.CameraLane, camera_name)
    if row is None:
        # main.js parity: absent calibration is data:null, not an error.
        return {"ok": True, "data": None}

    presigned = None
    if row.background_frame_url:
        try:
            key = extract_key(row.background_frame_url)
            if key:
                presigned = _store(request).presign_get(key)
        except Exception:  # pragma: no cover - store misconfiguration only
            # main.js parity: presign failure degrades to null, never breaks
            # the lanes payload the calibration UI needs.
            logger.warning(
                "background frame presign failed for %s", camera_name, exc_info=True
            )
    return {"ok": True, "data": _lanes_json(row, presigned)}


# Lane geometry drives where violations are detected, so the write path
# refuses payloads that cannot describe a real road: the editor works in
# NORMALISED coordinates (0..1 of the calibration frame), every shape needs
# enough points to be a shape, and the calibration frame must be a plausible
# pixel size. Previously any JSON at all was stored verbatim.
_LANE_COLLECTIONS = ("lanes", "stop_lines", "crossings", "detection_zones", "no_parking_zones")
# What the lane editor emits, in normalised 0..1 coordinates of the
# calibration frame (LaneConfigTab clamps every click to that range).
_NORMALISED_FIELDS = (
    "normalized_boundaries", "left_points", "right_points", "center_points",
)
# Legacy/opaque geometry: shape-checked but not range-checked, because older
# rows stored raw pixel coordinates under this key.
_LEGACY_FIELDS = ("points",)
_POINT_FIELDS = _NORMALISED_FIELDS + _LEGACY_FIELDS
_MAX_POINTS = 2000
_MAX_CALIBRATION = 16384


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _validate_points(where: str, pts, *, normalised: bool) -> None:
    if not isinstance(pts, list):
        raise _bad(f"{where}: points must be a list")
    if len(pts) > _MAX_POINTS:
        raise _bad(f"{where}: too many points ({len(pts)} > {_MAX_POINTS})")
    for i, p in enumerate(pts):
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise _bad(f"{where}[{i}]: each point must be [x, y]")
        for v in p:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise _bad(f"{where}[{i}]: coordinates must be numbers")
            if normalised and not (0.0 <= float(v) <= 1.0):
                raise _bad(
                    f"{where}[{i}]: coordinates are normalised to 0..1 of the "
                    f"calibration frame (got {v})"
                )


def _validate_lane_payload(body: LanesPut) -> None:
    w = int(body.calibration_width or 0)
    h = int(body.calibration_height or 0)
    if w < 0 or h < 0 or w > _MAX_CALIBRATION or h > _MAX_CALIBRATION:
        raise _bad("calibration frame must be between 0 and 16384 pixels per side")

    data = body.lane_data
    if data is None or data == {} or data == []:
        return  # clearing a camera's geometry is legitimate
    if not isinstance(data, dict):
        raise _bad("lane_data must be an object of shape collections")

    unknown = [k for k in data if k not in _LANE_COLLECTIONS]
    if unknown:
        raise _bad(f"unknown lane collection(s): {', '.join(sorted(unknown))}")

    total = 0
    for name in _LANE_COLLECTIONS:
        shapes = data.get(name)
        if shapes is None:
            continue
        if not isinstance(shapes, list):
            raise _bad(f"{name} must be a list")
        for idx, shape in enumerate(shapes):
            if not isinstance(shape, dict):
                raise _bad(f"{name}[{idx}] must be an object")
            found = [f for f in _POINT_FIELDS if f in shape]
            if not found:
                raise _bad(f"{name}[{idx}]: no geometry (expected one of {', '.join(_POINT_FIELDS)})")
            for f in found:
                _validate_points(
                    f"{name}[{idx}].{f}", shape[f], normalised=f in _NORMALISED_FIELDS
                )
            total += 1
    if total == 0 and any(isinstance(data.get(n), list) and data.get(n) for n in _LANE_COLLECTIONS):
        raise _bad("lane_data contains no usable shapes")


@router.put("/cameras/{camera_name}/lanes")
def put_camera_lanes(
    camera_name: str,
    body: LanesPut,
    user: models.User = Depends(_manage_gate),
    db: Session = Depends(get_db),
) -> dict:
    _validate_lane_payload(body)

    # UPSERT (main.js ON CONFLICT parity). No FK onto cameras — camera_lanes
    # keys by NAME and the legacy schema never enforced one either.
    row = db.get(models.CameraLane, camera_name)
    created = row is None
    if created:
        row = models.CameraLane(camera_name=camera_name)
        db.add(row)
    row.lane_data = body.lane_data if body.lane_data is not None else {}
    row.calibration_width = int(body.calibration_width or 0)
    row.calibration_height = int(body.calibration_height or 0)
    row.updated_at = models._utcnow()

    lanes = row.lane_data.get("lanes") if isinstance(row.lane_data, dict) else row.lane_data
    audit.record(
        db,
        officer=user.username,
        action="camera_change",
        notes=f"lanes {'created' if created else 'updated'} for {camera_name}",
        detail={
            "cameraName": camera_name,
            "op": "lanes_upsert",
            "created": created,
            "laneCount": len(lanes) if isinstance(lanes, list) else 0,
            "calibrationWidth": row.calibration_width,
            "calibrationHeight": row.calibration_height,
        },
    )
    db.commit()
    # No presign on the write path — the caller re-GETs for a fresh URL.
    return {"ok": True, "data": _lanes_json(row, None)}
