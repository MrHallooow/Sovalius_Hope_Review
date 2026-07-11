"use strict";
/**
 * Gateway client for the H.O.P.E. Review desktop app.
 *
 * The Electron MAIN process talks to the review gateway (FastAPI, port 8090)
 * over localhost HTTP with this module. It replaces the old direct-Postgres
 * (`pg`) + direct-S3 (`@aws-sdk/*`) + client-side bcrypt model entirely:
 * the ONLY credential this process ever holds is the JWT pair minted by
 * POST /auth/login, and it lives in main-process memory only (never on disk,
 * never in the renderer).
 *
 * Contract notes:
 *  - Uses Node 18+ global fetch (Electron 33 main process has it).
 *  - Gateway errors arrive TOP-LEVEL {code, message, retryable}; every method
 *    here maps them to the {ok:false, error:<string>} shape the renderer has
 *    always received from the IPC handlers (plus code/retryable as extra,
 *    additive fields). Network failures map the same way.
 *  - Refresh-on-401-once: when a bearer-authenticated call 401s, ONE refresh
 *    (serialized across concurrent callers — parallel refreshes would trip
 *    the gateway's token-family reuse detection) is attempted, then the call
 *    is retried once.
 *  - Every list/read method reshapes gateway rows back into the LEGACY row
 *    shape the renderer consumes (src/services/useDbData.js mapViolationRow
 *    reads violation_type/speed_mph/license_plate/coordinates/feed_name/
 *    timestamp/extra_data/remote_*_url; LaneConfigTab reads snake_case lane
 *    columns) so src/ needs zero changes.
 */

const DEFAULT_URL = "http://127.0.0.1:8090";

let baseUrl = DEFAULT_URL;

// JWT pair — MAIN-PROCESS MEMORY ONLY. Never persisted, never sent to the
// renderer (auth:login strips tokens before answering the IPC call).
const tokens = { access: null, refresh: null };

// Callers (db:test-connection) that must not run until a login minted tokens.
let loginWaiters = [];
// Serialize refresh: concurrent 401s must share ONE /auth/refresh call, or
// the second presentation of the rotated-out token revokes the whole family.
let refreshInFlight = null;

function init(url) {
  baseUrl = String(url || DEFAULT_URL).replace(/\/+$/, "");
}

function getBaseUrl() {
  return baseUrl;
}

function isLoggedIn() {
  return !!tokens.access;
}

/** Resolves once a login has minted tokens (immediately if already logged in). */
function waitForLogin() {
  if (tokens.access) return Promise.resolve();
  return new Promise((resolve) => loginWaiters.push(resolve));
}

function _releaseLoginWaiters() {
  const waiters = loginWaiters;
  loginWaiters = [];
  for (const w of waiters) w();
}

/** Local-store presigned URLs may be relative (/evidence/blob/...) when the
 *  gateway has no GWREV_PUBLIC_URL configured — absolutize so the renderer's
 *  <video>/<img> tags can load them from any origin. */
function absolutize(u) {
  if (!u || typeof u !== "string") return u ?? null;
  return u.startsWith("/") ? baseUrl + u : u;
}

async function _refreshOnce() {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const rt = tokens.refresh;
      if (!rt) return false;
      try {
        const res = await fetch(baseUrl + "/auth/refresh", {
          method: "POST",
          headers: { "content-type": "application/json", accept: "application/json" },
          body: JSON.stringify({ refreshToken: rt }),
        });
        if (!res.ok) {
          // Rotation refused (revoked / expired / reuse-detected): drop the
          // dead pair so the next call surfaces a clean 401 to the renderer.
          tokens.access = null;
          tokens.refresh = null;
          return false;
        }
        const data = await res.json();
        tokens.access = data.accessToken || null;
        tokens.refresh = data.refreshToken || null;
        return !!tokens.access;
      } catch {
        return false; // network blip — keep current tokens, surface the 401
      }
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/**
 * Core request. Returns {ok:true, status, data} or
 * {ok:false, status, error, code, retryable} — never throws.
 */
async function request(method, path, opts = {}, _isRetry = false) {
  const { body, query, auth = true } = opts;
  let url;
  try {
    url = new URL(baseUrl + path);
  } catch (err) {
    return { ok: false, status: 0, error: `Bad gateway URL: ${err.message}`, code: "config_error", retryable: false };
  }
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
  }
  const headers = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  const hasAuth = auth && !!tokens.access;
  if (hasAuth) headers.authorization = `Bearer ${tokens.access}`;

  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    return {
      ok: false,
      status: 0,
      error: `Gateway unreachable: ${err.message}`,
      code: "network_error",
      retryable: true,
    };
  }

  let data = null;
  const text = await res.text().catch(() => "");
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (res.ok) return { ok: true, status: res.status, data };

  // Refresh-on-401-once — only when this call actually presented a bearer
  // token (a failed LOGIN is a 401 too, but auth:false / no token attached).
  if (res.status === 401 && hasAuth && tokens.refresh && !_isRetry) {
    const refreshed = await _refreshOnce();
    if (refreshed) return request(method, path, opts, true);
  }

  // Map the gateway's top-level {code,message,retryable} to the legacy
  // {ok:false, error} the renderer reads; keep code/retryable additively.
  return {
    ok: false,
    status: res.status,
    error: (data && data.message) || `Gateway error (HTTP ${res.status})`,
    code: (data && data.code) || "error",
    retryable: !!(data && data.retryable),
  };
}

function _fail(r, extra = {}) {
  return { ok: false, error: r.error, code: r.code, retryable: r.retryable, ...extra };
}

// --------------------------------------------------------------------------
// Health / readiness
// --------------------------------------------------------------------------

/** GET /ready — DB + evidence-store probe. No bearer auth required. */
async function testConnection() {
  const r = await request("GET", "/ready", { auth: false });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

// --------------------------------------------------------------------------
// Auth
// --------------------------------------------------------------------------

/** POST /auth/login. Tokens stay HERE; the caller gets the legacy
 *  {ok, user{id,username,name,role,privileges,preferences,keybinds,theme}}. */
async function login(username, password) {
  const r = await request("POST", "/auth/login", {
    auth: false,
    body: { username: String(username ?? ""), password: String(password ?? "") },
  });
  if (!r.ok) return _fail(r);
  tokens.access = r.data.accessToken || null;
  tokens.refresh = r.data.refreshToken || null;
  if (tokens.access) _releaseLoginWaiters();
  return { ok: true, user: r.data.user };
}

function _legacyUserRow(u) {
  // Legacy auth:list-users / auth:register rows used the DB column names.
  return {
    id: u.id,
    username: u.username,
    display_name: u.name,
    role: u.role,
    privileges: u.privileges || {},
    active: u.active,
    created_at: u.createdAt ?? null,
    last_login: u.lastLogin ?? null,
  };
}

async function register(userData) {
  const r = await request("POST", "/auth/register", {
    body: {
      username: userData?.username,
      password: userData?.password,
      displayName: userData?.displayName ?? userData?.display_name ?? "",
      role: userData?.role || "officer",
      privileges: userData?.privileges || {},
    },
  });
  if (!r.ok) return _fail(r);
  return { ok: true, user: _legacyUserRow(r.data.user) };
}

async function listUsers() {
  const r = await request("GET", "/auth/users");
  if (!r.ok) return _fail(r);
  return { ok: true, users: (r.data.users || []).map(_legacyUserRow) };
}

async function updateUser(userId, fields) {
  const allowed = {};
  if (fields && typeof fields === "object") {
    if (fields.display_name !== undefined) allowed.display_name = fields.display_name;
    if (fields.role !== undefined) allowed.role = fields.role;
    if (fields.privileges !== undefined) allowed.privileges = fields.privileges;
    if (fields.active !== undefined) allowed.active = fields.active;
  }
  const r = await request("PATCH", `/auth/users/${encodeURIComponent(userId)}`, { body: allowed });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

async function changePassword(userId, newPassword) {
  const r = await request("POST", `/auth/users/${encodeURIComponent(userId)}/password`, {
    body: { password: newPassword },
  });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

async function deleteUser(userId) {
  const r = await request("DELETE", `/auth/users/${encodeURIComponent(userId)}`);
  if (!r.ok) return _fail(r);
  return { ok: true };
}

// --------------------------------------------------------------------------
// Violations / reviews / audit
// --------------------------------------------------------------------------

/** Reshape a gateway violation row into the LEGACY live-DB row the renderer's
 *  mapViolationRow() reads. Gateway names are kept too (additive). */
function _legacyViolationRow(r) {
  return {
    ...r,
    violation_type: r.type,
    speed_mph: r.speed ?? null,
    license_plate: r.plate || "",
    vehicle_class: r.vehicle || "",
    coordinates:
      r.gps_lat != null || r.gps_lng != null
        ? { lat: r.gps_lat ?? null, lng: r.gps_lng ?? null }
        : null,
    feed_name: r.camera || "",
    timestamp: r.date,
    extra_data: {
      speed_limit: r.speed_limit ?? null,
      weather: r.weather || "",
      ai_summary: r.ai_summary || "",
    },
    severity: r.severity ?? null,
    track_id: r.track_id ?? null,
    screenshot_path: r.screenshot_path ?? null,
    clip_path: r.clip_path ?? null,
    remote_clip_url: r.clip_url || null,
    remote_raw_clip_url: r.raw_clip_url || null,
    remote_screenshot_url: r.screenshot_url || null,
  };
}

async function getViolations() {
  const r = await request("GET", "/violations");
  if (!r.ok) return _fail(r, { rows: [] });
  return { ok: true, rows: (r.data.rows || []).map(_legacyViolationRow) };
}

/** PATCH /violations/{id}/review. Only status/notes/pinned travel — the
 *  gateway sets reviewed_by (token user) + reviewed_at (server clock) and
 *  APPENDS history itself; client-supplied values for those are dropped. */
async function updateViolationReview(violationId, fields) {
  const body = {};
  if (fields && typeof fields === "object") {
    if (fields.status !== undefined) body.status = fields.status;
    if (fields.notes !== undefined) body.notes = fields.notes;
    if (fields.pinned !== undefined) body.pinned = fields.pinned;
  }
  const r = await request(
    "PATCH",
    `/violations/${encodeURIComponent(violationId)}/review`,
    { body }
  );
  if (!r.ok) return _fail(r);
  return { ok: true, row: r.data.row };
}

async function getAuditLog() {
  const r = await request("GET", "/audit/log", { query: { limit: 1000 } });
  if (!r.ok) return _fail(r, { rows: [] });
  const rows = (r.data.items || []).map((it) => ({
    id: it.auditRef, // legacy serial id column is retired; auditRef is the display id
    seq: it.seq,
    officer: it.officer,
    action: it.action,
    violation_id: it.violationId || "",
    violationId: it.violationId || "",
    at: it.at,
    notes: it.notes || "",
  }));
  return { ok: true, rows };
}

async function getAnalytics() {
  const r = await request("GET", "/analytics");
  if (!r.ok) return _fail(r);
  return { ok: true, data: r.data.data };
}

// --------------------------------------------------------------------------
// Cameras + lanes
// --------------------------------------------------------------------------

async function getCameras() {
  const r = await request("GET", "/cameras");
  if (!r.ok) return _fail(r, { rows: [] });
  const rows = (r.data.items || []).map((c) => ({
    id: c.id,
    location: c.location,
    status: c.status,
    last_ping: c.lastPing ?? null,
    lastPing: c.lastPing ?? null,
  }));
  return { ok: true, rows };
}

async function updateCamera(id, fields) {
  const body = {};
  if (fields && typeof fields === "object") {
    if (fields.location !== undefined) body.location = fields.location;
    if (fields.status !== undefined) body.status = fields.status;
  }
  const r = await request("PATCH", `/cameras/${encodeURIComponent(id)}`, { body });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

function _legacyLanesRow(d) {
  if (!d) return null;
  return {
    camera_name: d.cameraName,
    lane_data: d.laneData ?? {},
    calibration_width: d.calibrationWidth ?? 0,
    calibration_height: d.calibrationHeight ?? 0,
    background_frame_url: d.backgroundFrameUrl ?? null,
    background_frame_at: d.backgroundFrameAt ?? null,
    background_frame_presigned: absolutize(d.backgroundFramePresigned) ?? null,
    updated_at: d.updatedAt ?? null,
  };
}

async function getCameraLanes(cameraName) {
  const r = await request("GET", `/cameras/${encodeURIComponent(cameraName)}/lanes`);
  if (!r.ok) return _fail(r);
  return { ok: true, data: _legacyLanesRow(r.data.data) };
}

async function getAllCameraLanes() {
  const r = await request("GET", "/camera-lanes");
  if (!r.ok) return _fail(r, { rows: [] });
  return { ok: true, rows: r.data.rows || [] }; // endpoint already emits legacy names
}

async function saveCameraLanes(cameraName, laneData, calWidth, calHeight) {
  const r = await request("PUT", `/cameras/${encodeURIComponent(cameraName)}/lanes`, {
    body: {
      lane_data: laneData ?? {},
      calibration_width: calWidth || 0,
      calibration_height: calHeight || 0,
    },
  });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

// --------------------------------------------------------------------------
// Evidence
// --------------------------------------------------------------------------

async function getEvidenceUrls(rawClipUrl, rawScreenshotUrl, rawRawClipUrl) {
  const r = await request("GET", "/evidence/urls", {
    query: {
      clipUrl: rawClipUrl || undefined,
      screenshotUrl: rawScreenshotUrl || undefined,
      rawClipUrl: rawRawClipUrl || undefined,
    },
  });
  if (!r.ok) return _fail(r);
  return {
    ok: true,
    clipUrl: absolutize(r.data.clipUrl),
    rawUrl: absolutize(r.data.rawUrl),
    screenshotUrl: absolutize(r.data.screenshotUrl),
    // Phase 3 CPU-erasure (review side): tracks.json sidecar, derived
    // server-side as a sibling of the raw clip. Null when the rack never
    // shipped one (old evidence) — the renderer treats that as "no overlay
    // data available", not an error.
    tracksUrl: absolutize(r.data.tracksUrl),
  };
}

// --------------------------------------------------------------------------
// Notifications / services / system / prefs
// --------------------------------------------------------------------------

async function getNotifications() {
  const r = await request("GET", "/notifications");
  if (!r.ok) return _fail(r, { rows: [] });
  return { ok: true, rows: r.data.rows || [] };
}

async function markNotificationRead(id) {
  const r = await request("PATCH", `/notifications/${encodeURIComponent(id)}`, { body: { read: true } });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

async function markAllNotificationsRead() {
  const r = await request("POST", "/notifications/mark-all-read", { body: {} });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

async function getServices() {
  const r = await request("GET", "/services");
  if (!r.ok) return _fail(r, { rows: [] });
  const rows = (r.data.services || []).map((s) => ({
    id: s.id,
    name: s.name,
    status: s.status,
    detail: s.detail,
    uptime: s.uptime,
    latency: s.latency,
    usage: s.usage,
    updated_at: s.updatedAt ?? null,
  }));
  return { ok: true, rows };
}

async function updateService(id, fields) {
  const body = {};
  if (fields && typeof fields === "object") {
    for (const k of ["status", "detail", "uptime", "latency", "usage"]) {
      if (fields[k] !== undefined) body[k] = fields[k];
    }
  }
  const r = await request("PATCH", `/services/${encodeURIComponent(id)}`, { body });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

async function getSystemStatus() {
  const r = await request("GET", "/system/status");
  if (!r.ok) return _fail(r, { row: null });
  const row = r.data.row;
  if (!row) return { ok: true, row: null };
  // The legacy system_status table was a WIDE row (feed_details, active_feeds,
  // uptime_sec, ...). The gateway stores that payload as a JSON `detail` blob —
  // flatten it back so the renderer's SystemStatus screen reads its fields.
  const detail = row.detail && typeof row.detail === "object" ? row.detail : {};
  return {
    ok: true,
    row: { ...detail, id: row.id, timestamp: row.timestamp, status: row.status },
  };
}

/** Prefs are the TOKEN user's own row; the legacy client-supplied userId is
 *  deliberately ignored (one user can no longer read/write another's prefs). */
async function loadPrefs() {
  const r = await request("GET", "/prefs");
  if (!r.ok) return _fail(r);
  return {
    ok: true,
    preferences: r.data.preferences || {},
    keybinds: r.data.keybinds || {},
    theme: r.data.theme || "dark",
  };
}

async function savePrefs(prefs, keybinds, theme) {
  const r = await request("PUT", "/prefs", {
    body: { preferences: prefs ?? {}, keybinds: keybinds ?? {}, theme: theme ?? undefined },
  });
  if (!r.ok) return _fail(r);
  return { ok: true };
}

module.exports = {
  init,
  getBaseUrl,
  isLoggedIn,
  waitForLogin,
  absolutize,
  request,
  testConnection,
  login,
  register,
  listUsers,
  updateUser,
  changePassword,
  deleteUser,
  getViolations,
  updateViolationReview,
  getAuditLog,
  getAnalytics,
  getCameras,
  updateCamera,
  getCameraLanes,
  getAllCameraLanes,
  saveCameraLanes,
  getEvidenceUrls,
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  getServices,
  updateService,
  getSystemStatus,
  loadPrefs,
  savePrefs,
};
