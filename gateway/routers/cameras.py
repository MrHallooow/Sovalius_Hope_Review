"""Cameras + lane calibration.

GET   /cameras                  (bearer auth)            — main.js db:get-cameras
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


@router.put("/cameras/{camera_name}/lanes")
def put_camera_lanes(
    camera_name: str,
    body: LanesPut,
    user: models.User = Depends(_manage_gate),
    db: Session = Depends(get_db),
) -> dict:
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
