const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hopeDb", {
  testConnection: () => ipcRenderer.invoke("db:test-connection"),
  query: (sql, params) => ipcRenderer.invoke("db:query", sql, params),
  getViolations: () => ipcRenderer.invoke("db:get-violations"),
  getCameras: () => ipcRenderer.invoke("db:get-cameras"),
  getAuditLog: () => ipcRenderer.invoke("db:get-audit-log"),
  updateViolation: (id, fields) =>
    ipcRenderer.invoke("db:update-violation", id, fields),
  insertAudit: (entry) => ipcRenderer.invoke("db:insert-audit", entry),
  getNotifications: () => ipcRenderer.invoke("db:get-notifications"),
  markNotificationRead: (id) =>
    ipcRenderer.invoke("db:mark-notification-read", id),
  markAllNotificationsRead: () =>
    ipcRenderer.invoke("db:mark-all-notifications-read"),
  updateCamera: (id, fields) =>
    ipcRenderer.invoke("db:update-camera", id, fields),
  getAnalytics: () => ipcRenderer.invoke("db:get-analytics"),
  getServices: () => ipcRenderer.invoke("db:get-services"),
  updateService: (id, fields) =>
    ipcRenderer.invoke("db:update-service", id, fields),
  getSystemStatus: () => ipcRenderer.invoke("db:get-system-status"),
  getCameraLanes: (cameraName) => ipcRenderer.invoke("db:get-camera-lanes", cameraName),
  getAllCameraLanes: () => ipcRenderer.invoke("db:get-all-camera-lanes"),
  saveCameraLanes: (cameraName, laneData, calWidth, calHeight) =>
    ipcRenderer.invoke("db:save-camera-lanes", cameraName, laneData, calWidth, calHeight),
});

contextBridge.exposeInMainWorld("hopeAuth", {
  login: (username, password) =>
    ipcRenderer.invoke("auth:login", username, password),
  register: (userData) => ipcRenderer.invoke("auth:register", userData),
  listUsers: () => ipcRenderer.invoke("auth:list-users"),
  updateUser: (userId, fields) =>
    ipcRenderer.invoke("auth:update-user", userId, fields),
  changePassword: (userId, newPassword) =>
    ipcRenderer.invoke("auth:change-password", userId, newPassword),
  logout: () => ipcRenderer.invoke("auth:logout"),
  deleteUser: (userId) => ipcRenderer.invoke("auth:delete-user", userId),
});

contextBridge.exposeInMainWorld("hopeSystem", {
  // Real, pre-login gateway readiness — what the splash screen reports.
  gatewayHealth: () => ipcRenderer.invoke("system:gateway-health"),
});

contextBridge.exposeInMainWorld("hopeEvidence", {
  // Evidence is addressed by CASE, never by object key.
  getUrls: (violationId) => ipcRenderer.invoke("evidence:get-urls", violationId),
});

contextBridge.exposeInMainWorld("hopePrefs", {
  load: (userId) => ipcRenderer.invoke("prefs:load", userId),
  save: (userId, prefs, keybinds, theme) =>
    ipcRenderer.invoke("prefs:save", userId, prefs, keybinds, theme),
});

contextBridge.exposeInMainWorld("hopeUpdater", {
  onStatus: (callback) => {
    ipcRenderer.on("update-status", (_event, data) => callback(data));
  },
  check: () => ipcRenderer.invoke("updater:check"),
  download: () => ipcRenderer.invoke("updater:download"),
  install: () => ipcRenderer.invoke("updater:install"),
  getVersion: () => ipcRenderer.invoke("updater:get-version"),
});
