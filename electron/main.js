const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const { autoUpdater } = require("electron-updater");
const gateway = require("./gatewayClient.js");

const isDev = !app.isPackaged;

// ── Configuration ──
// The ONLY config this app needs is the review-gateway URL. All database,
// object-storage and credential handling lives behind the gateway (FastAPI,
// port 8090); this process never holds a DB password or an AWS key.
if (isDev) {
  // Dev: .env at the repo root — contains GATEWAY_URL and nothing else.
  require("dotenv").config({ path: path.join(__dirname, "..", ".env") });
  // `npm run dev` always brings Vite up on 5173 (wait-on gates electron), and
  // the dev-server URL is not a secret — default it so the pruned .env stays
  // gateway-URL-only.
  if (!process.env.VITE_DEV_SERVER_URL) {
    process.env.VITE_DEV_SERVER_URL = "http://localhost:5173";
  }
} else {
  // Packaged: optional .env next to the app (electron-builder extraResources)
  // lets ops point at a different gateway without rebuilding...
  try {
    require("dotenv").config({ path: path.join(process.resourcesPath, ".env") });
  } catch {
    /* optional */
  }
  // ...falling back to the bundled default (gateway URL only — the old
  // embedded-credential config.production.js is retired).
  if (!process.env.GATEWAY_URL) {
    try {
      const prodCfg = require("./config.production.js");
      if (prodCfg && prodCfg.GATEWAY_URL) process.env.GATEWAY_URL = prodCfg.GATEWAY_URL;
    } catch {
      /* fall through to the client default */
    }
  }
}

gateway.init(process.env.GATEWAY_URL);

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
// Channel names and response shapes are IDENTICAL to the legacy direct-PG
// handlers so the renderer (src/) needs zero changes. Every handler now
// delegates to gatewayClient, which reshapes gateway responses back into the
// legacy row shapes and maps gateway {code,message,retryable} errors to the
// {ok:false, error} the renderer reads.

ipcMain.handle("db:test-connection", async () => {
  // The renderer calls this ONCE at mount — before login — and gates every
  // later read/write on its result. The legacy direct-PG pool needed no auth,
  // so data loads worked pre-login; the gateway requires a token. Waiting for
  // the first successful login here reproduces the legacy timing exactly:
  // the promise resolves the moment tokens exist, then useDbData's initial
  // violations/cameras/audit fetches run authenticated.
  await gateway.waitForLogin();
  return gateway.testConnection();
});

ipcMain.handle("db:query", async () => {
  // Raw SQL from the renderer is retired with the direct-PG model — the
  // gateway API is the only data path. (src/ never invoked this channel.)
  return {
    ok: false,
    error: "Raw SQL is disabled: the review app now talks to the gateway API only",
  };
});

ipcMain.handle("db:get-violations", async () => {
  return gateway.getViolations();
});

ipcMain.handle("db:get-cameras", async () => {
  return gateway.getCameras();
});

ipcMain.handle("db:get-audit-log", async () => {
  return gateway.getAuditLog();
});

ipcMain.handle("db:update-violation", async (_event, violationId, fields) => {
  // Only status/notes/pinned travel to the gateway. reviewed_by/reviewed_at/
  // history are SERVER-derived (token user + server clock, history appended
  // server-side) — client-supplied values are no longer trusted anywhere.
  return gateway.updateViolationReview(violationId, fields || {});
});

ipcMain.handle("db:insert-audit", async () => {
  // Audit rows are written SERVER-SIDE on every review/user/camera mutation
  // (tamper-evident hash chain). A client-supplied audit row is untrusted by
  // design, so this legacy channel is an acknowledged no-op — the renderer
  // fire-and-forgets it right after db:update-violation, which already
  // produced the authoritative audit row.
  return { ok: true, row: null };
});

// ── Services IPC ──

ipcMain.handle("db:get-services", async () => {
  return gateway.getServices();
});

ipcMain.handle("db:update-service", async (_event, id, fields) => {
  return gateway.updateService(id, fields || {});
});

// ── User Preferences IPC ──

ipcMain.handle("prefs:load", async () => {
  // Target row comes from the bearer token — the legacy client-supplied
  // userId is ignored (one user can no longer read another's prefs).
  return gateway.loadPrefs();
});

ipcMain.handle("prefs:save", async (_event, _userId, prefs, keybinds, theme) => {
  return gateway.savePrefs(prefs, keybinds, theme);
});

// ── Notifications IPC ──

ipcMain.handle("db:get-notifications", async () => {
  return gateway.getNotifications();
});

ipcMain.handle("db:mark-notification-read", async (_event, id) => {
  return gateway.markNotificationRead(id);
});

ipcMain.handle("db:mark-all-notifications-read", async () => {
  return gateway.markAllNotificationsRead();
});

// ── Camera CRUD IPC ──

ipcMain.handle("db:update-camera", async (_event, id, fields) => {
  return gateway.updateCamera(id, fields || {});
});

// ── System Status IPC ──

ipcMain.handle("db:get-system-status", async () => {
  return gateway.getSystemStatus();
});

// ── Analytics IPC ──

ipcMain.handle("db:get-analytics", async () => {
  return gateway.getAnalytics();
});

// ── Auth IPC Handlers ──

ipcMain.handle("auth:login", async (_event, username, password) => {
  // Tokens live in gatewayClient (main-process memory ONLY) — the renderer
  // receives the legacy {ok, user} shape with no token material.
  return gateway.login(username, password);
});

ipcMain.handle("auth:register", async (_event, userData) => {
  return gateway.register(userData || {});
});

ipcMain.handle("auth:list-users", async () => {
  return gateway.listUsers();
});

ipcMain.handle("auth:update-user", async (_event, userId, fields) => {
  return gateway.updateUser(userId, fields || {});
});

ipcMain.handle("auth:change-password", async (_event, userId, newPassword) => {
  // Hashing happens IN the gateway (bcrypt server-side); the password only
  // transits the localhost request body — no client-side bcryptjs anymore.
  return gateway.changePassword(userId, newPassword);
});

ipcMain.handle("auth:delete-user", async (_event, userId) => {
  return gateway.deleteUser(userId); // soft delete (active=false) server-side
});

// ── Evidence pre-signed URLs (via gateway; no AWS credentials here) ──

ipcMain.handle("evidence:get-urls", async (_event, rawClipUrl, rawScreenshotUrl, rawRawClipUrl) => {
  return gateway.getEvidenceUrls(rawClipUrl, rawScreenshotUrl, rawRawClipUrl);
});

// ── Camera Lanes ──

ipcMain.handle("db:get-camera-lanes", async (_event, cameraName) => {
  return gateway.getCameraLanes(cameraName);
});

ipcMain.handle("db:get-all-camera-lanes", async () => {
  return gateway.getAllCameraLanes();
});

ipcMain.handle("db:save-camera-lanes", async (_event, cameraName, laneData, calWidth, calHeight) => {
  return gateway.saveCameraLanes(cameraName, laneData, calWidth, calHeight);
});

// ── Auto-updater ──

let splashWin = null;

function sendSplash(js) {
  if (splashWin && !splashWin.isDestroyed()) {
    splashWin.webContents.executeJavaScript(js).catch(() => {});
  }
}

function sendUpdateStatus(status, data = {}) {
  const wins = BrowserWindow.getAllWindows().filter((w) => w !== splashWin);
  if (wins.length > 0) {
    wins[0].webContents.send("update-status", { status, ...data });
  }
}

function setupAutoUpdater() {
  autoUpdater.autoDownload = true;
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

function createSplash() {
  splashWin = new BrowserWindow({
    width: 360,
    height: 220,
    frame: false,
    resizable: false,
    transparent: true,
    center: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  splashWin.loadFile(path.join(__dirname, "splash.html"));
  splashWin.on("closed", () => { splashWin = null; });
  return splashWin;
}

function checkForUpdateOnSplash() {
  return new Promise((resolve) => {
    const TIMEOUT_MS = 15000;
    let settled = false;

    const finish = () => {
      if (settled) return;
      settled = true;
      if (splashWin && !splashWin.isDestroyed()) {
        splashWin.close();
      }
      resolve();
    };

    const timeout = setTimeout(() => {
      sendSplash(`document.getElementById('status').textContent='Starting…'`);
      finish();
    }, TIMEOUT_MS);

    autoUpdater.once("update-not-available", () => {
      clearTimeout(timeout);
      sendSplash(`document.getElementById('status').textContent='Up to date'`);
      setTimeout(finish, 600);
    });

    autoUpdater.once("error", () => {
      clearTimeout(timeout);
      sendSplash(`document.getElementById('status').textContent='Starting…'`);
      setTimeout(finish, 400);
    });

    autoUpdater.once("update-available", (info) => {
      clearTimeout(timeout);
      sendSplash(
        `document.getElementById('status').textContent='Downloading v${info.version}…'`
      );
    });

    autoUpdater.on("download-progress", (prog) => {
      const pct = Math.round(prog.percent);
      sendSplash(`
        document.getElementById('status').textContent='Downloading… ${pct}%';
        var b=document.getElementById('bar');
        b.classList.remove('indeterminate');
        b.style.width='${pct}%';
      `);
    });

    autoUpdater.once("update-downloaded", (info) => {
      clearTimeout(timeout);
      sendSplash(
        `document.getElementById('status').textContent='Installing v${info.version}…'`
      );
      setTimeout(() => {
        autoUpdater.quitAndInstall(false, true);
      }, 1000);
    });

    autoUpdater.checkForUpdates().catch(() => {
      clearTimeout(timeout);
      finish();
    });
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

app.whenReady().then(async () => {
  setupAutoUpdater();

  if (app.isPackaged) {
    createSplash();
    await checkForUpdateOnSplash();
  }

  createWindow();

  if (app.isPackaged) {
    setInterval(() => {
      autoUpdater.checkForUpdates().catch(() => {});
    }, 5 * 60 * 1000);
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
