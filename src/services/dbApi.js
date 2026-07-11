const isElectron = typeof window !== "undefined" && window.hopeDb;

export async function testConnection() {
  if (!isElectron) return { ok: false, error: "Not running in Electron" };
  return window.hopeDb.testConnection();
}

export async function getViolations() {
  if (!isElectron) return { ok: false, rows: [], error: "No DB (demo mode)" };
  return window.hopeDb.getViolations();
}

export async function getCameras() {
  if (!isElectron) return { ok: false, rows: [], error: "No DB (demo mode)" };
  return window.hopeDb.getCameras();
}

export async function getAuditLog() {
  if (!isElectron) return { ok: false, rows: [], error: "No DB (demo mode)" };
  return window.hopeDb.getAuditLog();
}

export async function updateViolation(id, fields) {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.updateViolation(id, fields);
}

export async function insertAudit(entry) {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.insertAudit(entry);
}

export async function rawQuery(sql, params) {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.query(sql, params);
}

export async function getNotifications() {
  if (!isElectron) return { ok: false, rows: [], error: "No DB (demo mode)" };
  return window.hopeDb.getNotifications();
}

export async function markNotificationRead(id) {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.markNotificationRead(id);
}

export async function markAllNotificationsRead() {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.markAllNotificationsRead();
}

export async function updateCamera(id, fields) {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.updateCamera(id, fields);
}

export async function getAnalytics() {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.getAnalytics();
}

export async function getEvidenceUrls(remoteClipUrl, remoteScreenshotUrl, remoteRawClipUrl) {
  if (!remoteClipUrl && !remoteScreenshotUrl) return null;
  if (typeof window === "undefined" || !window.hopeEvidence) return null;
  return window.hopeEvidence.getUrls(remoteClipUrl, remoteScreenshotUrl, remoteRawClipUrl);
}

export async function getCameraLanes(cameraName) {
  if (!isElectron) return { ok: false, data: null, error: "No DB (demo mode)" };
  return window.hopeDb.getCameraLanes(cameraName);
}

export async function getAllCameraLanes() {
  if (!isElectron) return { ok: false, rows: [], error: "No DB (demo mode)" };
  return window.hopeDb.getAllCameraLanes();
}

export async function saveCameraLanes(cameraName, laneData, calWidth, calHeight) {
  if (!isElectron) return { ok: false, error: "No DB (demo mode)" };
  return window.hopeDb.saveCameraLanes(cameraName, laneData, calWidth, calHeight);
}

export function isDbAvailable() {
  return !!isElectron;
}

/**
 * Fetch + parse a tracks.json sidecar (Phase 3 CPU-erasure, review side).
 * `url` is the presigned/absolutized tracksUrl from getEvidenceUrls() —
 * fetched directly by the renderer exactly like the <video>/<img> tags fetch
 * clipUrl/screenshotUrl. Absence (404, network error, bad JSON, or a schema
 * that doesn't validate) all resolve to null — never throws — so callers can
 * treat "no overlay data" as a single, cleanly-checked case.
 */
export async function fetchTracksJson(url) {
  if (!url) return null;
  try {
    const res = await fetch(url);
    if (!res.ok) return null; // 404 -> older evidence with no sidecar
    const data = await res.json();
    return data;
  } catch {
    return null;
  }
}
