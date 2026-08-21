"use strict";
/**
 * DIRECT Postgres/S3 client for the H.O.P.E. Review desktop app.
 *
 * This is the v1.6.2 data path, restored: the Electron MAIN process talks
 * straight to Postgres and presigns S3 itself, with no gateway process to
 * start. It exposes the EXACT same module surface as gatewayClient.js, so
 * main.js chooses one or the other and every IPC handler, channel name and
 * row shape stays identical -- src/ needs no changes either way.
 *
 * DELIBERATE TRADE-OFF (read before extending this file)
 * -----------------------------------------------------
 * Commit a2845d0 moved this app behind a gateway specifically so the desktop
 * never held a database credential. Running direct means the DB password and
 * AWS keys live on every reviewer machine again, and these protections that
 * the gateway enforced SERVER-side become client-side only, i.e. advisory:
 *   * per-transition privilege checks (canApprove / canDismiss / canRevise)
 *   * the tamper-evident hash-chained audit log (this path writes plain rows)
 *   * refresh-token rotation and session revocation
 * Anyone who can run this app can also run psql with the same credentials, so
 * treat every check here as UI guidance, not as enforcement.
 *
 * WHERE THE CREDENTIALS COME FROM
 * -------------------------------
 * The environment only -- in practice the `.env` that electron-builder copies
 * into the installer as extraResources. That file is gitignored, so unlike
 * the old electron/config.production.js it never reaches the public repo
 * (SECURITY_INCIDENT_RUNBOOK.md). It DOES ship inside the .exe, so anyone
 * holding an installer can extract it: distribute builds accordingly, and
 * rotate if one leaves your control. Nothing is hard-coded here -- if PGHOST
 * is absent the app reports a configuration error instead of falling back to
 * anything embedded.
 */

const fs = require("fs");
const path = require("path");
const { Pool } = require("pg");
const bcrypt = require("bcryptjs");
const { S3Client, GetObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

/** Amazon's public RDS CA bundle (not a secret; shipped with the app). */
let _caCache;
function _rdsCa() {
  if (_caCache !== undefined) return _caCache;
  for (const p of [
    path.join(__dirname, "rds-ca-global.pem"),
    path.join(process.resourcesPath || "", "rds-ca-global.pem"),
  ]) {
    try {
      if (p && fs.existsSync(p)) {
        _caCache = fs.readFileSync(p, "utf8");
        return _caCache;
      }
    } catch { /* try the next location */ }
  }
  // Without the bundle, fail closed: an unverified TLS session to a database
  // holding evidence is worse than a clear error.
  _caCache = undefined;
  return undefined;
}

let pool = null;
let s3 = null;
let cfg = {};
let currentUser = null; // the signed-in user row; auth state for this process
let loginWaiters = [];

// --------------------------------------------------------------------------
// Setup
// --------------------------------------------------------------------------

function init() {
  cfg = {
    host: process.env.PGHOST || "",
    port: parseInt(process.env.PGPORT || "5432", 10),
    database: process.env.PGDATABASE || "",
    user: process.env.PGUSER || "",
    password: process.env.PGPASSWORD || "",
    ssl: String(process.env.PGSSL || "").toLowerCase(),
    region: process.env.AWS_REGION || "us-east-1",
    bucket: process.env.S3_BUCKET || "",
    urlTtl: parseInt(process.env.EVIDENCE_URL_TTL || "3600", 10),
  };
  if (!cfg.host) return; // configuration error surfaced by testConnection()

  pool = new Pool({
    host: cfg.host,
    port: cfg.port,
    database: cfg.database,
    user: cfg.user,
    password: cfg.password,
    // Verify the server certificate against Amazon's RDS CA bundle, which
    // ships next to this file. The pre-gateway code used
    // rejectUnauthorized:false instead, which accepts ANY certificate --
    // including an attacker's -- making the encryption decorative.
    ssl: ["1", "true", "yes", "require"].includes(cfg.ssl)
      ? { rejectUnauthorized: true, ca: _rdsCa() }
      : false,
    max: 5,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 15000,
  });
  pool.on("error", () => { /* idle client dropped; pg re-establishes on demand */ });

  if (cfg.bucket && process.env.AWS_ACCESS_KEY_ID) {
    s3 = new S3Client({
      region: cfg.region,
      credentials: {
        accessKeyId: process.env.AWS_ACCESS_KEY_ID,
        secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
      },
    });
  }
}

function getBaseUrl() {
  return cfg.host ? `postgres://${cfg.host}/${cfg.database}` : "(not configured)";
}

function isLoggedIn() {
  return !!currentUser;
}

function waitForLogin() {
  if (currentUser) return Promise.resolve();
  return new Promise((resolve) => loginWaiters.push(resolve));
}

function _releaseLoginWaiters() {
  const w = loginWaiters;
  loginWaiters = [];
  for (const f of w) f();
}

/** S3/plain URLs are already absolute; kept for gatewayClient parity. */
function absolutize(u) {
  return u ?? null;
}

function _fail(err, extra = {}) {
  const msg = err && err.message ? err.message : String(err || "Database error");
  return { ok: false, error: msg, code: "db_error", retryable: true, ...extra };
}

async function q(sql, params = []) {
  if (!pool) throw new Error("Database is not configured (PGHOST missing)");
  const c = await pool.connect();
  try {
    return await c.query(sql, params);
  } finally {
    c.release();
  }
}

/** Compatibility shim: gatewayClient exposes request(); nothing uses it here. */
async function request() {
  return { ok: false, status: 0, error: "Not applicable in direct mode", code: "unsupported" };
}

// --------------------------------------------------------------------------
// Health
// --------------------------------------------------------------------------

async function testConnection() {
  if (!cfg.host) {
    return {
      ok: false,
      error: "No database configured. Put PGHOST/PGDATABASE/PGUSER/PGPASSWORD in the .env next to the app.",
      code: "config_error",
      retryable: false,
    };
  }
  try {
    await q("select 1");
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

// --------------------------------------------------------------------------
// Auth  (bcrypt against users.password -- the same hashes 1.6.2 used)
// --------------------------------------------------------------------------

function _userOut(u) {
  return {
    id: u.id,
    username: u.username,
    name: u.display_name || u.username,
    role: u.role,
    privileges: u.privileges || {},
    preferences: u.preferences || {},
    keybinds: u.keybinds || {},
    theme: u.theme || "dark",
  };
}

function _legacyUserRow(u) {
  return {
    id: u.id,
    username: u.username,
    display_name: u.display_name,
    role: u.role,
    privileges: u.privileges || {},
    active: u.active,
    created_at: u.created_at ?? null,
    last_login: u.last_login ?? null,
  };
}

async function login(username, password) {
  try {
    const r = await q(
      "select * from users where lower(username)=lower($1) and active=true limit 1",
      [String(username ?? "")]
    );
    // Uniform failure message: never reveal whether the account exists.
    const bad = { ok: false, error: "Invalid username or password", code: "unauthorized", retryable: false };
    if (r.rowCount === 0) {
      // Constant-ish work even on a miss, so timing does not leak existence.
      await bcrypt.compare(String(password ?? ""), "$2b$12$" + "x".repeat(53));
      return bad;
    }
    const u = r.rows[0];
    if (!(await bcrypt.compare(String(password ?? ""), u.password || ""))) return bad;

    currentUser = u;
    _releaseLoginWaiters();
    await q("update users set last_login=now() where id=$1", [u.id]).catch(() => {});
    await _audit(u, "login", null, "");
    return { ok: true, user: _userOut(u) };
  } catch (e) {
    return _fail(e);
  }
}

async function logout() {
  // Direct mode holds no tokens; dropping the identity is the whole session.
  currentUser = null;
  loginWaiters = [];
  return { ok: true };
}

async function register(userData) {
  if (!_can("canManageUsers")) return _denied("canManageUsers");
  try {
    const hash = await bcrypt.hash(String(userData?.password ?? ""), 12);
    const r = await q(
      `insert into users (username,password,display_name,role,privileges,active,preferences,keybinds,theme,created_at)
       values ($1,$2,$3,$4,$5,true,'{}'::jsonb,'{}'::jsonb,'dark',now()) returning *`,
      [userData?.username, hash, userData?.displayName ?? userData?.display_name ?? "",
       userData?.role || "officer", JSON.stringify(userData?.privileges || {})]
    );
    await _audit(currentUser, "user_admin", null, `created ${userData?.username}`);
    return { ok: true, user: _legacyUserRow(r.rows[0]) };
  } catch (e) {
    return _fail(e);
  }
}

async function listUsers() {
  if (!_can("canManageUsers")) return _denied("canManageUsers", { users: [] });
  try {
    const r = await q("select * from users order by id");
    return { ok: true, users: r.rows.map(_legacyUserRow) };
  } catch (e) {
    return _fail(e, { users: [] });
  }
}

async function updateUser(userId, fields) {
  if (!_can("canManageUsers")) return _denied("canManageUsers");
  const sets = [], vals = [];
  const add = (col, v) => { vals.push(v); sets.push(`${col}=$${vals.length}`); };
  if (fields?.display_name !== undefined) add("display_name", fields.display_name);
  if (fields?.role !== undefined) add("role", fields.role);
  if (fields?.privileges !== undefined) add("privileges", JSON.stringify(fields.privileges));
  if (fields?.active !== undefined) add("active", !!fields.active);
  if (!sets.length) return { ok: true };
  try {
    vals.push(userId);
    await q(`update users set ${sets.join(",")} where id=$${vals.length}`, vals);
    await _audit(currentUser, "user_admin", null, `updated user ${userId}`);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

async function changePassword(userId, newPassword) {
  if (!_can("canManageUsers")) return _denied("canManageUsers");
  try {
    const hash = await bcrypt.hash(String(newPassword ?? ""), 12);
    await q("update users set password=$1 where id=$2", [hash, userId]);
    await _audit(currentUser, "user_admin", null, `password reset for user ${userId}`);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

async function deleteUser(userId) {
  if (!_can("canManageUsers")) return _denied("canManageUsers");
  try {
    await q("update users set active=false where id=$1", [userId]); // soft delete
    await _audit(currentUser, "user_admin", null, `deactivated user ${userId}`);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

function _can(priv) {
  const p = (currentUser && currentUser.privileges) || {};
  return p[priv] === true;
}

function _denied(priv, extra = {}) {
  return { ok: false, error: `${priv} privilege required`, code: "forbidden", retryable: false, ...extra };
}

// --------------------------------------------------------------------------
// Violations
// --------------------------------------------------------------------------

// The renderer (src/services/useDbData.js mapViolationRow) reads the device
// -sync column names, which is exactly what this database stores -- so rows
// pass through nearly as-is, plus the review columns from the LEFT JOIN.
const VIOLATION_SELECT = `
  select v.*,
         coalesce(r.status,'pending') as review_status,
         r.reviewed_by               as reviewed_by,
         r.reviewed_at               as reviewed_at,
         coalesce(r.notes,'')        as review_notes,
         coalesce(r.pinned,false)    as review_pinned,
         coalesce(r.history,'[]'::jsonb) as review_history
    from violations v
    left join violation_reviews r on r.violation_id = v.id
`;

async function getViolations() {
  try {
    const r = await q(`${VIOLATION_SELECT} order by v.timestamp desc nulls last, v.id desc limit 2000`);
    return {
      ok: true,
      rows: r.rows.map((v) => ({
        ...v,
        // This schema predates the rack enforcement gate, so eligibility is
        // undetermined rather than false. The desk renders that as "no
        // citation is minted until the gate confirms".
        citable: v.citable ?? null,
        gateReason: v.gate_reason || "",
      })),
    };
  } catch (e) {
    return _fail(e, { rows: [] });
  }
}

/**
 * Record a review decision. Mirrors the gateway's PATCH .../review contract:
 * the caller gets {ok, row} with the row that was actually written, or
 * {ok:false,error} -- the desk shows nothing as decided until this says ok.
 */
async function updateViolationReview(violationId, fields) {
  if (!currentUser) return { ok: false, error: "Not signed in", code: "unauthorized", retryable: false };
  const wantStatus = fields?.status;
  const actor = currentUser.display_name || currentUser.username;

  try {
    const cur = await q(
      `select v.citable, v.clip_path, v.remote_clip_url, v.remote_raw_clip_url,
              v.remote_screenshot_url, r.status as review_status, r.history
         from violations v
         left join violation_reviews r on r.violation_id=v.id
        where v.id=$1`,
      [violationId]
    );
    if (cur.rowCount === 0) return { ok: false, error: "Unknown violation", code: "not_found", retryable: false };
    const row = cur.rows[0];
    const from = row.review_status || "pending";

    if (wantStatus && wantStatus !== from) {
      if (!["pending", "approved", "dismissed"].includes(wantStatus)) {
        return { ok: false, error: "Invalid status", code: "bad_request", retryable: false };
      }
      // Privilege checks -- ADVISORY in direct mode (see the file header).
      if (from !== "pending" && !_can("canRevise")) return _denied("canRevise");
      if (wantStatus === "approved" && !_can("canApprove")) return _denied("canApprove");
      if (wantStatus === "dismissed" && !_can("canDismiss")) return _denied("canDismiss");
      // Enforcement gate: never record an approval the citation bridge is
      // certain to reject. Only an explicit false blocks; undetermined does
      // not, or every pre-gate row would be un-approvable.
      if (wantStatus === "approved" && row.citable === false) {
        return { ok: false, error: "Not eligible for citation approval", code: "not_citable", retryable: false };
      }
    }

    const history = Array.isArray(row.history) ? row.history : [];
    const changed = wantStatus !== undefined && wantStatus !== from;
    const nextHistory = changed
      ? history.concat([{ action: wantStatus, by: actor, at: new Date().toISOString(), notes: fields?.notes || "" }])
      : history;

    const sets = [], vals = [violationId];
    const add = (col, v) => { vals.push(v); sets.push(`${col}=$${vals.length}`); };
    if (wantStatus !== undefined) {
      add("status", wantStatus);
      // reviewer + timestamp are derived HERE, never taken from the renderer.
      add("reviewed_by", actor);
      add("reviewed_at", new Date());
    }
    if (fields?.notes !== undefined) add("notes", fields.notes);
    if (fields?.pinned !== undefined) add("pinned", !!fields.pinned);
    add("history", JSON.stringify(nextHistory));

    await q(
      `insert into violation_reviews (violation_id,status,reviewed_by,reviewed_at,notes,pinned,history)
       values ($1,$2,$3,$4,$5,$6,$7)
       on conflict (violation_id) do update set ${sets.join(",")}`,
      [violationId, wantStatus || from, changed ? actor : null, changed ? new Date() : null,
       fields?.notes ?? "", !!fields?.pinned, JSON.stringify(nextHistory)]
    ).catch(async (e) => {
      // Older copies of this table have no unique constraint on violation_id.
      if (!/no unique|constraint/i.test(e.message)) throw e;
      const ex = await q("select 1 from violation_reviews where violation_id=$1", [violationId]);
      if (ex.rowCount) {
        await q(`update violation_reviews set ${sets.join(",")} where violation_id=$1`, vals);
      } else {
        await q(
          `insert into violation_reviews (violation_id,status,reviewed_by,reviewed_at,notes,pinned,history)
           values ($1,$2,$3,$4,$5,$6,$7)`,
          [violationId, wantStatus || from, actor, new Date(), fields?.notes ?? "",
           !!fields?.pinned, JSON.stringify(nextHistory)]
        );
      }
    });

    if (changed) {
      const action = wantStatus === "approved" ? "review_approved"
        : wantStatus === "dismissed" ? "review_dismissed" : "review_reopened";
      await _audit(currentUser, action, violationId, fields?.notes || "");
    } else if (fields?.notes !== undefined) {
      await _audit(currentUser, "review_notes", violationId, fields.notes || "");
    }

    const out = await q("select * from violation_reviews where violation_id=$1", [violationId]);
    return { ok: true, row: out.rows[0] || null };
  } catch (e) {
    return _fail(e);
  }
}

// --------------------------------------------------------------------------
// Audit
// --------------------------------------------------------------------------

async function _audit(user, action, violationId, notes) {
  try {
    await q(
      "insert into audit_log (officer,action,violation_id,at,notes) values ($1,$2,$3,now(),$4)",
      [user ? user.username : "system", action, violationId, String(notes || "").slice(0, 512)]
    );
  } catch { /* audit must never block the action it records */ }
}

async function getAuditLog() {
  try {
    const r = await q("select * from audit_log order by at desc limit 1000");
    return { ok: true, rows: r.rows };
  } catch (e) {
    return _fail(e, { rows: [] });
  }
}

// --------------------------------------------------------------------------
// Evidence  (CASE-BOUND: keys come from the violation row, never the caller)
// --------------------------------------------------------------------------

function _key(url) {
  if (!url) return null;
  const s = String(url).trim();
  if (!s) return null;
  try {
    const u = new URL(s);
    const k = u.pathname.replace(/^\/+/, "");
    return k || null;
  } catch {
    return s.startsWith("/") ? null : s; // bare key
  }
}

async function _presign(url) {
  const key = _key(url);
  if (!key) return null;
  if (!s3 || !cfg.bucket) return null;
  try {
    return await getSignedUrl(s3, new GetObjectCommand({ Bucket: cfg.bucket, Key: key }),
      { expiresIn: cfg.urlTtl });
  } catch {
    return null;
  }
}

async function getEvidenceUrls(violationId) {
  if (!currentUser) return { ok: false, error: "Not signed in", code: "unauthorized", retryable: false };
  const id = String(violationId ?? "").trim();
  if (!id) return { ok: false, error: "No violation id", code: "bad_request", retryable: false };
  try {
    const r = await q(
      "select remote_clip_url, remote_raw_clip_url, remote_screenshot_url from violations where id=$1",
      [id]
    );
    if (r.rowCount === 0) return { ok: false, error: "Unknown violation", code: "not_found", retryable: false };
    const v = r.rows[0];
    const rawKey = _key(v.remote_raw_clip_url);
    const tracksKey = rawKey ? rawKey.replace(/[^/]+$/, "tracks.json") : null;
    const [clipUrl, rawUrl, screenshotUrl, tracksUrl] = await Promise.all([
      _presign(v.remote_clip_url),
      _presign(v.remote_raw_clip_url),
      _presign(v.remote_screenshot_url),
      tracksKey ? _presign(tracksKey) : Promise.resolve(null),
    ]);
    await _audit(currentUser, "evidence_accessed", id, "");
    return { ok: true, clipUrl, rawUrl, screenshotUrl, tracksUrl };
  } catch (e) {
    return _fail(e);
  }
}

// --------------------------------------------------------------------------
// Cameras / lanes
// --------------------------------------------------------------------------

async function getCameras() {
  try {
    const r = await q("select * from cameras order by id");
    return { ok: true, rows: r.rows };
  } catch (e) {
    return _fail(e, { rows: [] });
  }
}

async function updateCamera(id, fields) {
  if (!_can("canManageCameras")) return _denied("canManageCameras");
  const sets = [], vals = [];
  const add = (c, v) => { vals.push(v); sets.push(`${c}=$${vals.length}`); };
  if (fields?.location !== undefined) add("location", fields.location);
  if (fields?.status !== undefined) add("status", fields.status);
  if (!sets.length) return { ok: true };
  try {
    vals.push(id);
    await q(`update cameras set ${sets.join(",")} where id=$${vals.length}`, vals);
    await _audit(currentUser, "camera_change", null, `camera ${id}`);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

function _lanesRow(d) {
  if (!d) return null;
  return {
    camera_name: d.camera_name,
    lane_data: d.lane_data,
    calibration_width: d.calibration_width,
    calibration_height: d.calibration_height,
    background_frame_url: d.background_frame_url ?? null,
    background_frame_presigned: null,
    background_frame_at: d.background_frame_at ?? null,
    updated_at: d.updated_at ?? null,
  };
}

async function getCameraLanes(cameraName) {
  try {
    const r = await q("select * from camera_lanes where camera_name=$1", [cameraName]);
    const row = _lanesRow(r.rows[0]);
    if (row && row.background_frame_url) {
      row.background_frame_presigned = await _presign(row.background_frame_url);
    }
    return { ok: true, data: row };
  } catch (e) {
    return _fail(e, { data: null });
  }
}

async function getAllCameraLanes() {
  try {
    const r = await q("select * from camera_lanes order by camera_name");
    return { ok: true, rows: r.rows.map(_lanesRow) };
  } catch (e) {
    return _fail(e, { rows: [] });
  }
}

async function saveCameraLanes(cameraName, laneData, calWidth, calHeight) {
  if (!_can("canManageCameras")) return _denied("canManageCameras");
  try {
    await q(
      `insert into camera_lanes (camera_name,lane_data,calibration_width,calibration_height,updated_at)
       values ($1,$2,$3,$4,now())
       on conflict (camera_name) do update set
         lane_data=$2, calibration_width=$3, calibration_height=$4, updated_at=now()`,
      [cameraName, JSON.stringify(laneData ?? {}), calWidth || 0, calHeight || 0]
    );
    await _audit(currentUser, "camera_change", null, `lanes for ${cameraName}`);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

// --------------------------------------------------------------------------
// Notifications / services / system / prefs / analytics
// --------------------------------------------------------------------------

async function getNotifications() {
  try {
    const r = await q("select * from notifications order by at desc, id desc limit 50");
    return { ok: true, rows: r.rows };
  } catch (e) {
    return _fail(e, { rows: [] });
  }
}

async function markNotificationRead(id) {
  try {
    await q("update notifications set read=true where id=$1", [id]);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

async function markAllNotificationsRead() {
  try {
    const r = await q("update notifications set read=true where read=false");
    return { ok: true, updated: r.rowCount };
  } catch (e) {
    return _fail(e);
  }
}

async function getServices() {
  try {
    const r = await q("select * from services order by id");
    return { ok: true, rows: r.rows };
  } catch (e) {
    return _fail(e, { rows: [] });
  }
}

async function updateService(id, fields) {
  const sets = [], vals = [];
  const add = (c, v) => { vals.push(v); sets.push(`${c}=$${vals.length}`); };
  if (fields?.status !== undefined) add("status", fields.status);
  if (fields?.detail !== undefined) add("detail", fields.detail);
  if (!sets.length) return { ok: true };
  try {
    vals.push(id);
    await q(`update services set ${sets.join(",")}, updated_at=now() where id=$${vals.length}`, vals);
    await _audit(currentUser, "service_change", null, `service ${id}`);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
}

async function getSystemStatus() {
  try {
    const r = await q("select * from system_status order by timestamp desc limit 1");
    return { ok: true, row: r.rows[0] || null };
  } catch (e) {
    return _fail(e, { row: null });
  }
}

async function getAnalytics() {
  try {
    const r = await q(
      `select coalesce(r.status,'pending') as status, count(*)::int as n
         from violations v left join violation_reviews r on r.violation_id=v.id
        group by 1`
    );
    const by = {};
    for (const x of r.rows) by[x.status] = x.n;
    const total = Object.values(by).reduce((a, b) => a + b, 0);
    return {
      ok: true,
      analytics: {
        total,
        approved: by.approved || 0,
        dismissed: by.dismissed || 0,
        pending: by.pending || 0,
      },
    };
  } catch (e) {
    return _fail(e);
  }
}

async function loadPrefs() {
  if (!currentUser) return { ok: true, preferences: {}, keybinds: {}, theme: "dark" };
  try {
    const r = await q("select preferences,keybinds,theme from users where id=$1", [currentUser.id]);
    const u = r.rows[0] || {};
    return {
      ok: true,
      preferences: u.preferences || {},
      keybinds: u.keybinds || {},
      theme: u.theme || "dark",
    };
  } catch (e) {
    return _fail(e, { preferences: {}, keybinds: {}, theme: "dark" });
  }
}

async function savePrefs(prefs, keybinds, theme) {
  if (!currentUser) return { ok: false, error: "Not signed in", code: "unauthorized", retryable: false };
  try {
    await q("update users set preferences=$1, keybinds=$2, theme=$3 where id=$4", [
      JSON.stringify(prefs ?? {}), JSON.stringify(keybinds ?? {}), theme || "dark", currentUser.id,
    ]);
    return { ok: true };
  } catch (e) {
    return _fail(e);
  }
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
  logout,
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
