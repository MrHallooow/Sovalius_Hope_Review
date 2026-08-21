import { useState, useEffect, useCallback } from "react";
import {
  testConnection,
  getViolations,
  getCameras,
  getAuditLog,
  updateViolation,
  isDbAvailable,
} from "./dbApi.js";

function snakeToCamel(obj) {
  if (Array.isArray(obj)) return obj.map(snakeToCamel);
  if (obj === null || typeof obj !== "object") return obj;
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    const ck = k.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    out[ck] = v;
  }
  return out;
}

function parseCoords(c) {
  if (!c) return { lat: null, lng: null };
  if (typeof c === "string") try { c = JSON.parse(c); } catch { return { lat: null, lng: null }; }
  if (Array.isArray(c)) return { lat: c[0], lng: c[1] };
  return { lat: c.lat ?? c.latitude ?? null, lng: c.lng ?? c.longitude ?? null };
}

function mapViolationRow(r) {
  const extra = r.extra_data || {};
  return {
    id: r.id,
    type: r.violation_type || "Unknown",
    speed: r.speed_mph ?? null,
    limit: extra.speed_limit ?? null,
    plate: r.license_plate || "",
    vehicle: r.vehicle_class || "",
    location: r.location || "",
    gps: parseCoords(r.coordinates),
    cameras: r.feed_name ? [r.feed_name] : [],
    camera: r.feed_name || "",
    date: r.timestamp,
    confidence: r.confidence != null && r.confidence <= 1 ? Math.round(r.confidence * 1000) / 10 : r.confidence,
    weather: extra.weather || "",
    aiSummary: extra.ai_summary || "",
    severity: r.severity || "medium",
    status: r.review_status || "pending",
    reviewedBy: r.reviewed_by || null,
    reviewedAt: r.reviewed_at || null,
    notes: r.review_notes ?? "",
    pinned: r.review_pinned ?? false,
    history: r.review_history || [],
    trackId: r.track_id,
    screenshotPath: r.screenshot_path,
    clipPath: r.clip_path,
    remoteClipUrl: r.remote_clip_url || null,
    remoteRawClipUrl: r.remote_raw_clip_url || null,
    remoteScreenshotUrl: r.remote_screenshot_url || null,
    // Rack enforcement gate. `citable === false` means this case can never
    // become a citation (the gateway refuses to record an approval for it);
    // `null` means eligibility is not yet determined. Either way the reviewer
    // must SEE it before deciding — see the gate banner in the review view.
    citable: r.citable ?? null,
    gateReason: r.gateReason || r.gate_reason || "",
  };
}

function mapCameraRow(r) {
  return {
    id: r.id,
    location: r.location,
    status: r.status,
    lastPing: r.lastPing ?? r.last_ping,
  };
}

function mapAuditRow(r) {
  return {
    id: r.id,
    officer: r.officer,
    action: r.action,
    violationId: r.violationId ?? r.violation_id,
    at: r.at,
    notes: r.notes || "",
  };
}

export function useDbData(fallbackViolations, fallbackCameras, fallbackAudit) {
  const [dbConnected, setDbConnected] = useState(false);
  const [dbError, setDbError] = useState(null);
  const [violations, setViolations] = useState(fallbackViolations);
  const [cameras, setCameras] = useState(fallbackCameras);
  const [auditLog, setAuditLog] = useState(fallbackAudit);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      if (!isDbAvailable()) {
        setLoading(false);
        return;
      }

      const connResult = await testConnection();
      if (cancelled) return;

      if (!connResult.ok) {
        setDbError(connResult.error);
        setLoading(false);
        return;
      }

      setDbConnected(true);

      const [vRes, cRes, aRes] = await Promise.all([
        getViolations(),
        getCameras(),
        getAuditLog(),
      ]);

      if (cancelled) return;

      if (vRes.ok) {
        setViolations(vRes.rows.map(mapViolationRow));
      }
      if (cRes.ok) {
        setCameras(cRes.rows.map(mapCameraRow));
      }
      if (aRes.ok) {
        setAuditLog(aRes.rows.map(mapAuditRow));
      }

      setLoading(false);
    }

    init();
    return () => { cancelled = true; };
  }, []);

  /**
   * Record a review decision. THE SERVER IS AUTHORITATIVE.
   *
   * Resolves to `{ok:true, row}` carrying the review row the gateway actually
   * wrote, or `{ok:false, error}` — callers must not show a decision as
   * recorded until this says ok. reviewed_by / reviewed_at / history are
   * server-derived (token user + server clock) and are never sent from here;
   * the tamper-evident audit row is written server-side in the same
   * transaction, so no client-side audit entry is fabricated either.
   */
  const persistAction = useCallback(
    async (violationId, status, notes) => {
      if (!dbConnected) {
        return { ok: false, error: "Not connected to the review gateway" };
      }
      const res = await updateViolation(violationId, { status, notes });
      if (res && res.ok) return { ok: true, row: res.row || null };
      return { ok: false, error: (res && res.error) || "The gateway rejected this decision" };
    },
    [dbConnected]
  );

  /** Persist a pin. Pins are part of the review record, not local UI state. */
  const persistPin = useCallback(
    async (violationId, pinned) => {
      if (!dbConnected) {
        return { ok: false, error: "Not connected to the review gateway" };
      }
      const res = await updateViolation(violationId, { pinned: !!pinned });
      if (res && res.ok) return { ok: true, row: res.row || null };
      return { ok: false, error: (res && res.error) || "The gateway rejected this change" };
    },
    [dbConnected]
  );

  const refreshViolations = useCallback(async () => {
    if (!dbConnected) return;
    const res = await getViolations();
    if (res.ok && res.rows.length > 0) {
      setViolations(res.rows.map(mapViolationRow));
    }
  }, [dbConnected]);

  const refreshAll = useCallback(async () => {
    if (!dbConnected) return;
    const [vRes, aRes] = await Promise.all([
      getViolations(),
      getAuditLog(),
    ]);
    if (vRes.ok) setViolations(vRes.rows.map(mapViolationRow));
    if (aRes.ok) setAuditLog(aRes.rows.map(mapAuditRow));
  }, [dbConnected]);

  useEffect(() => {
    if (!dbConnected) return;
    const i = setInterval(refreshAll, 15000);
    return () => clearInterval(i);
  }, [dbConnected, refreshAll]);

  /**
   * Drop every loaded case, audit row and camera on sign-out.
   *
   * Clearing dbConnected also tears down the 15s refresh interval, so a
   * signed-out desk stops polling the gateway. A second reviewer at the same
   * desk starts from an empty app and must authenticate before any case is
   * fetched again.
   */
  const reset = useCallback(() => {
    setDbConnected(false);
    setDbError(null);
    setViolations([]);
    setCameras([]);
    setAuditLog([]);
    setLoading(false);
  }, []);

  return {
    reset,
    dbConnected,
    dbError,
    loading,
    violations,
    setViolations,
    cameras,
    setCameras,
    auditLog,
    setAuditLog,
    persistAction,
    persistPin,
    refreshViolations,
    refreshAll,
  };
}
