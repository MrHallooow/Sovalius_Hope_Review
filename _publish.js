const https = require("https");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const OWNER = "MrHallooow";
const REPO = "Sovalius_Hope_Review";

// The version comes from package.json — the same source electron-builder used
// to name the installer and to write dist/latest.yml. It used to be hard-coded
// (v1.6.2) and drifted: publishing would have uploaded the OLD installer
// alongside the NEW latest.yml, and every desk's auto-updater would then read
// "1.7.0 available", request HOPE-Review-Setup-1.7.0.exe, and 404.
const VERSION = require("./package.json").version;
const TAG = `v${VERSION}`;
const NAME = `v${VERSION}`;
const BODY = process.env.RELEASE_NOTES || `Release v${VERSION}`;

const ASSETS = [
  `dist/HOPE-Review-Setup-${VERSION}.exe`,
  `dist/HOPE-Review-Setup-${VERSION}.exe.blockmap`,
  "dist/latest.yml",
];

function getToken() {
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN;
  try {
    const out = execSync("git credential fill", { input: `protocol=https\nhost=github.com\n\n`, encoding: "utf8" });
    const m = out.match(/password=(.+)/);
    if (m) return m[1].trim();
  } catch {}
  throw new Error("No GitHub token found");
}

function api(method, endpoint, body) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: "api.github.com",
      path: endpoint,
      method,
      headers: {
        "User-Agent": "publish-script",
        Authorization: `token ${getToken()}`,
        Accept: "application/vnd.github.v3+json",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
    };
    const req = https.request(opts, (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => {
        try { resolve({ status: res.statusCode, data: JSON.parse(d || "{}") }); }
        catch { resolve({ status: res.statusCode, data: d }); }
      });
    });
    req.on("error", reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function upload(uploadUrl, filePath) {
  return new Promise((resolve, reject) => {
    const name = path.basename(filePath);
    const stat = fs.statSync(filePath);
    const url = new URL(uploadUrl.replace("{?name,label}", `?name=${encodeURIComponent(name)}`));
    const opts = {
      hostname: url.hostname,
      path: url.pathname + url.search,
      method: "POST",
      headers: {
        "User-Agent": "publish-script",
        Authorization: `token ${getToken()}`,
        "Content-Type": "application/octet-stream",
        "Content-Length": stat.size,
      },
    };
    const req = https.request(opts, (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => resolve({ status: res.statusCode, name }));
    });
    req.on("error", reject);
    fs.createReadStream(filePath).pipe(req);
  });
}

(async () => {
  // Verify EVERY asset exists before touching the remote release. This script
  // deletes the existing release for the tag before creating the new one, so a
  // missing file used to mean the old release was destroyed and nothing
  // replaced it.
  const missing = ASSETS.filter((f) => !fs.existsSync(f));
  if (missing.length) {
    console.error(`Refusing to publish ${TAG}: missing ${missing.join(", ")}`);
    console.error("Run `npm run package` first.");
    process.exit(1);
  }

  // latest.yml is what electron-updater reads; if it does not describe THIS
  // version the published release is self-inconsistent.
  const feed = fs.readFileSync("dist/latest.yml", "utf8");
  if (!feed.includes(`version: ${VERSION}`)) {
    console.error(`Refusing to publish: dist/latest.yml does not describe ${VERSION}.`);
    console.error("Re-run `npm run package` so the updater feed matches the installer.");
    process.exit(1);
  }

  console.log(`Publishing ${TAG} (${ASSETS.length} assets)`);
  console.log("NOTE: this installer is unsigned unless a signing certificate was configured.");
  console.log("Deleting old release if exists...");
  const old = await api("GET", `/repos/${OWNER}/${REPO}/releases/tags/${TAG}`);
  if (old.status === 200) {
    await api("DELETE", `/repos/${OWNER}/${REPO}/releases/${old.data.id}`);
    console.log("  Deleted old release");
  }
  try { await api("DELETE", `/repos/${OWNER}/${REPO}/git/refs/tags/${TAG}`); } catch {}

  console.log("Creating release...");
  const rel = await api("POST", `/repos/${OWNER}/${REPO}/releases`, {
    tag_name: TAG, name: NAME, body: BODY, draft: false, prerelease: false,
  });
  if (rel.status !== 201) { console.error("Create failed:", rel.data); process.exit(1); }
  console.log("  Release created:", rel.data.html_url);

  for (const f of ASSETS) {
    console.log(`Uploading ${path.basename(f)}...`);
    const r = await upload(rel.data.upload_url, f);
    console.log(`  ${r.name} -> ${r.status}`);
  }
  console.log("Done!", rel.data.html_url);
})();
