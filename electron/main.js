const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const { Pool } = require("pg");
const bcrypt = require("bcryptjs");
const { autoUpdater } = require("electron-updater");

const isDev = !app.isPackaged;
const rootDir = isDev
  ? path.join(__dirname, "..")
  : path.dirname(app.getPath("exe"));

const envCandidates = [
  path.join(rootDir, ".env"),
  path.join(process.resourcesPath || rootDir, ".env"),
  path.join(__dirname, "..", ".env"),
];
const envPath = envCandidates.find((p) => fs.existsSync(p));
if (envPath) {
  require("dotenv").config({ path: envPath });
} else {
  require("dotenv").config();
}

let pool = null;
let s3Client = null;

function getS3Client() {
  if (s3Client) return s3Client;
  const region = process.env.AWS_REGION;
  const accessKeyId = process.env.AWS_ACCESS_KEY_ID;
  const secretAccessKey = process.env.AWS_SECRET_ACCESS_KEY;
  if (!region || !accessKeyId || !secretAccessKey) return null;
  const { S3Client } = require("@aws-sdk/client-s3");
  s3Client = new S3Client({
    region,
    credentials: { accessKeyId, secretAccessKey },
  });
  return s3Client;
}

function extractS3Key(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.pathname.replace(/^\//, "");
  } catch {
    return null;
  }
}

function createPool() {
  const useSSL = process.env.PGSSL === "true";
  const cfg = {
    host: process.env.PGHOST || "localhost",
    port: parseInt(process.env.PGPORT || "5432", 10),
    database: process.env.PGDATABASE || "hope",
    user: process.env.PGUSER || "postgres",
    password: process.env.PGPASSWORD || "",
    max: 5,
    connectionTimeoutMillis: 10000,
    ...(useSSL && { ssl: { rejectUnauthorized: false } }),
  };
  pool = new Pool(cfg);
  pool.on("error", (err) => {
    console.error("Unexpected PostgreSQL pool error", err);
  });
  return pool;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "H.O.P.E. Review",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (isDev && process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(__dirname, "..", "dist-renderer", "index.html"));
  }
}

// ── IPC Handlers ──

ipcMain.handle("db:test-connection", async () => {
  try {
    if (!pool) createPool();
    const client = await pool.connect();
    await client.query("SELECT 1");
    client.release();
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("db:query", async (_event, sql, params) => {
  try {
    if (!pool) createPool();
    const result = await pool.query(sql, params);
    return { ok: true, rows: result.rows, rowCount: result.rowCount };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("db:get-violations", async () => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      `SELECT v.*,
         COALESCE(r.status, 'pending') AS review_status,
         r.reviewed_by, r.reviewed_at,
         COALESCE(r.notes, '') AS review_notes,
         COALESCE(r.pinned, false) AS review_pinned,
         COALESCE(r.history, '[]'::jsonb) AS review_history
       FROM violations v
       LEFT JOIN violation_reviews r ON r.violation_id = v.id
       ORDER BY v.timestamp DESC`
    );
    return { ok: true, rows };
  } catch (err) {
    return { ok: false, error: err.message, rows: [] };
  }
});

ipcMain.handle("db:get-cameras", async () => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT * FROM cameras ORDER BY id"
    );
    return { ok: true, rows };
  } catch (err) {
    return { ok: false, error: err.message, rows: [] };
  }
});

ipcMain.handle("db:get-audit-log", async () => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT * FROM audit_log ORDER BY at DESC"
    );
    return { ok: true, rows };
  } catch (err) {
    return { ok: false, error: err.message, rows: [] };
  }
});

ipcMain.handle("db:update-violation", async (_event, violationId, fields) => {
  try {
    if (!pool) createPool();
    const status = fields.status || "pending";
    const reviewedBy = fields.reviewed_by || null;
    const reviewedAt = fields.reviewed_at || null;
    const notes = fields.notes || "";
    const history = fields.history ? JSON.stringify(fields.history) : "[]";

    const { rows } = await pool.query(
      `INSERT INTO violation_reviews (violation_id, status, reviewed_by, reviewed_at, notes, pinned, history)
       VALUES ($1, $2, $3, $4, $5, false, $6::jsonb)
       ON CONFLICT (violation_id)
       DO UPDATE SET status = $2, reviewed_by = $3, reviewed_at = $4, notes = $5, history = $6::jsonb
       RETURNING *`,
      [violationId, status, reviewedBy, reviewedAt, notes, history]
    );
    return { ok: true, row: rows[0] };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("db:insert-audit", async (_event, entry) => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      `INSERT INTO audit_log (officer, action, violation_id, at, notes)
       VALUES ($1, $2, $3, $4, $5) RETURNING *`,
      [entry.officer, entry.action, entry.violationId, entry.at, entry.notes]
    );
    return { ok: true, row: rows[0] };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// ── Services IPC ──

ipcMain.handle("db:get-services", async () => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT * FROM services ORDER BY id"
    );
    return { ok: true, rows };
  } catch (err) {
    return { ok: false, error: err.message, rows: [] };
  }
});

ipcMain.handle("db:update-service", async (_event, id, fields) => {
  try {
    if (!pool) createPool();
    const keys = Object.keys(fields);
    const sets = keys.map((k, i) => `"${k}" = $${i + 2}`);
    const vals = [id, ...keys.map((k) => fields[k])];
    await pool.query(
      `UPDATE services SET ${sets.join(", ")}, updated_at = NOW() WHERE id = $1`,
      vals
    );
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// ── User Preferences IPC ──

ipcMain.handle("prefs:load", async (_event, userId) => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT preferences, keybinds, theme FROM users WHERE id = $1",
      [userId]
    );
    if (rows.length === 0) return { ok: false, error: "User not found" };
    return {
      ok: true,
      preferences: rows[0].preferences || {},
      keybinds: rows[0].keybinds || {},
      theme: rows[0].theme || "dark",
    };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("prefs:save", async (_event, userId, prefs, keybinds, theme) => {
  try {
    if (!pool) createPool();
    await pool.query(
      "UPDATE users SET preferences = $1, keybinds = $2, theme = $3 WHERE id = $4",
      [JSON.stringify(prefs), JSON.stringify(keybinds), theme, userId]
    );
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// ── Notifications IPC ──

ipcMain.handle("db:get-notifications", async () => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT * FROM notifications ORDER BY at DESC LIMIT 50"
    );
    return { ok: true, rows };
  } catch (err) {
    return { ok: false, error: err.message, rows: [] };
  }
});

ipcMain.handle("db:mark-notification-read", async (_event, id) => {
  try {
    if (!pool) createPool();
    await pool.query("UPDATE notifications SET read = true WHERE id = $1", [id]);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("db:mark-all-notifications-read", async () => {
  try {
    if (!pool) createPool();
    await pool.query("UPDATE notifications SET read = true WHERE read = false");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// ── Camera CRUD IPC ──

ipcMain.handle("db:update-camera", async (_event, id, fields) => {
  try {
    if (!pool) createPool();
    const keys = Object.keys(fields);
    const sets = keys.map((k, i) => `"${k}" = $${i + 2}`);
    const vals = [id, ...keys.map((k) => fields[k])];
    await pool.query(`UPDATE cameras SET ${sets.join(", ")} WHERE id = $1`, vals);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// ── System Status IPC ──

ipcMain.handle("db:get-system-status", async () => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT * FROM system_status ORDER BY timestamp DESC LIMIT 1"
    );
    return { ok: true, row: rows[0] || null };
  } catch (err) {
    return { ok: false, error: err.message, row: null };
  }
});

// ── Analytics IPC ──

ipcMain.handle("db:get-analytics", async () => {
  try {
    if (!pool) createPool();

    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const weekStart = new Date(todayStart);
    weekStart.setDate(weekStart.getDate() - 7);
    const monthStart = new Date(todayStart);
    monthStart.setDate(monthStart.getDate() - 30);

    const countQ = (since) => pool.query(
      `SELECT
         count(*) as total,
         count(*) FILTER (WHERE COALESCE(r.status,'pending')='approved') as approved,
         count(*) FILTER (WHERE COALESCE(r.status,'pending')='dismissed') as dismissed,
         count(*) FILTER (WHERE COALESCE(r.status,'pending')='pending') as pending
       FROM violations v
       LEFT JOIN violation_reviews r ON r.violation_id = v.id
       WHERE v.timestamp >= $1`,
      [since.toISOString()]
    );

    const [today, week, month] = await Promise.all([
      countQ(todayStart), countQ(weekStart), countQ(monthStart),
    ]);

    const typeRes = await pool.query(
      `SELECT v.violation_type as type, count(*)::int as count
       FROM violations v GROUP BY v.violation_type ORDER BY count DESC`
    );
    const totalAll = typeRes.rows.reduce((s, r) => s + r.count, 0) || 1;
    const byType = {};
    typeRes.rows.forEach((r) => { byType[r.type] = Math.round((r.count / totalAll) * 100); });

    const hourlyRes = await pool.query(
      `SELECT EXTRACT(HOUR FROM v.timestamp)::int as hr, count(*)::int as c
       FROM violations v WHERE v.timestamp >= $1
       GROUP BY hr ORDER BY hr`,
      [todayStart.toISOString()]
    );
    const hourly = new Array(24).fill(0);
    hourlyRes.rows.forEach((r) => { hourly[r.hr] = r.c; });

    const parse = (r) => ({
      total: parseInt(r.rows[0].total),
      approved: parseInt(r.rows[0].approved),
      dismissed: parseInt(r.rows[0].dismissed),
      pending: parseInt(r.rows[0].pending),
    });

    return {
      ok: true,
      data: {
        today: parse(today),
        week: parse(week),
        month: parse(month),
        byType,
        hourly,
      },
    };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// ── Auth IPC Handlers ──

ipcMain.handle("auth:login", async (_event, username, password) => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT * FROM users WHERE username = $1 AND active = true",
      [username.toLowerCase().trim()]
    );
    if (rows.length === 0) {
      return { ok: false, error: "Invalid username or password" };
    }
    const user = rows[0];
    const valid = await bcrypt.compare(password, user.password);
    if (!valid) {
      return { ok: false, error: "Invalid username or password" };
    }
    await pool.query("UPDATE users SET last_login = NOW() WHERE id = $1", [user.id]);
    return {
      ok: true,
      user: {
        id: user.id,
        username: user.username,
        name: user.display_name,
        role: user.role,
        privileges: user.privileges,
        preferences: user.preferences || {},
        keybinds: user.keybinds || {},
        theme: user.theme || "dark",
      },
    };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("auth:register", async (_event, userData) => {
  try {
    if (!pool) createPool();
    const existing = await pool.query("SELECT id FROM users WHERE username = $1", [
      userData.username.toLowerCase().trim(),
    ]);
    if (existing.rows.length > 0) {
      return { ok: false, error: "Username already exists" };
    }
    const hash = await bcrypt.hash(userData.password, 12);
    const { rows } = await pool.query(
      `INSERT INTO users (username, password, display_name, role, privileges)
       VALUES ($1, $2, $3, $4, $5) RETURNING id, username, display_name, role, privileges`,
      [
        userData.username.toLowerCase().trim(),
        hash,
        userData.displayName,
        userData.role || "officer",
        JSON.stringify(userData.privileges || {}),
      ]
    );
    return { ok: true, user: rows[0] };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("auth:list-users", async () => {
  try {
    if (!pool) createPool();
    const { rows } = await pool.query(
      "SELECT id, username, display_name, role, privileges, active, created_at, last_login FROM users ORDER BY id"
    );
    return { ok: true, users: rows };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("auth:update-user", async (_event, userId, fields) => {
  try {
    if (!pool) createPool();
    const allowed = ["display_name", "role", "privileges", "active"];
    const keys = Object.keys(fields).filter((k) => allowed.includes(k));
    if (keys.length === 0) return { ok: false, error: "No valid fields" };
    const sets = keys.map((k, i) => `"${k}" = $${i + 2}`);
    const vals = [userId, ...keys.map((k) => k === "privileges" ? JSON.stringify(fields[k]) : fields[k])];
    await pool.query(`UPDATE users SET ${sets.join(", ")} WHERE id = $1`, vals);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("auth:change-password", async (_event, userId, newPassword) => {
  try {
    if (!pool) createPool();
    const hash = await bcrypt.hash(newPassword, 12);
    await pool.query("UPDATE users SET password = $1 WHERE id = $2", [hash, userId]);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("auth:delete-user", async (_event, userId) => {
  try {
    if (!pool) createPool();
    await pool.query("UPDATE users SET active = false WHERE id = $1", [userId]);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

// ── Evidence S3 Pre-signed URLs ──

ipcMain.handle("evidence:get-urls", async (_event, rawClipUrl, rawScreenshotUrl, rawRawClipUrl) => {
  try {
    const client = getS3Client();
    if (!client) return { ok: false, error: "AWS credentials not configured" };
    const bucket = process.env.S3_BUCKET;
    if (!bucket) return { ok: false, error: "S3_BUCKET not configured" };

    const { GetObjectCommand } = require("@aws-sdk/client-s3");
    const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");
    const expiresIn = 3600;

    let clipUrl = null;
    let rawUrl = null;
    let screenshotUrl = null;

    const clipKey = extractS3Key(rawClipUrl);
    if (clipKey) {
      clipUrl = await getSignedUrl(client,
        new GetObjectCommand({ Bucket: bucket, Key: clipKey }),
        { expiresIn }
      );
    }

    const rawClipKey = extractS3Key(rawRawClipUrl);
    if (rawClipKey) {
      rawUrl = await getSignedUrl(client,
        new GetObjectCommand({ Bucket: bucket, Key: rawClipKey }),
        { expiresIn }
      );
    }

    const ssKey = extractS3Key(rawScreenshotUrl);
    if (ssKey) {
      screenshotUrl = await getSignedUrl(client,
        new GetObjectCommand({ Bucket: bucket, Key: ssKey }),
        { expiresIn }
      );
    }

    return { ok: true, clipUrl, rawUrl, screenshotUrl };
  } catch (err) {
    console.error("[evidence] error:", err.message);
    return { ok: false, error: err.message };
  }
});

// ── Auto-updater ──

function sendUpdateStatus(status, data = {}) {
  const wins = BrowserWindow.getAllWindows();
  if (wins.length > 0) {
    wins[0].webContents.send("update-status", { status, ...data });
  }
}

function setupAutoUpdater() {
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on("checking-for-update", () => {
    sendUpdateStatus("checking");
  });
  autoUpdater.on("update-available", (info) => {
    sendUpdateStatus("available", {
      version: info.version,
      releaseNotes: info.releaseNotes || "",
      releaseDate: info.releaseDate || "",
    });
  });
  autoUpdater.on("update-not-available", () => {
    sendUpdateStatus("up-to-date");
  });
  autoUpdater.on("download-progress", (prog) => {
    sendUpdateStatus("downloading", {
      percent: Math.round(prog.percent),
      transferred: prog.transferred,
      total: prog.total,
    });
  });
  autoUpdater.on("update-downloaded", (info) => {
    sendUpdateStatus("ready", { version: info.version });
  });
  autoUpdater.on("error", (err) => {
    sendUpdateStatus("error", { message: err?.message || String(err) });
  });
}

ipcMain.handle("updater:check", async () => {
  try {
    const result = await autoUpdater.checkForUpdates();
    return { ok: true, version: result?.updateInfo?.version };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("updater:download", async () => {
  try {
    await autoUpdater.downloadUpdate();
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("updater:install", () => {
  autoUpdater.quitAndInstall(false, true);
});

ipcMain.handle("updater:get-version", () => {
  return app.getVersion();
});

// ── App lifecycle ──

app.whenReady().then(() => {
  createPool();
  createWindow();
  setupAutoUpdater();

  if (app.isPackaged) {
    autoUpdater.checkForUpdates().catch(() => {});
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (pool) pool.end();
  if (process.platform !== "darwin") app.quit();
});
