const https = require("https");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const OWNER = "MrHallooow";
const REPO = "Sovalius_Hope_Review";
const TAG = "v1.6.0";
const NAME = "v1.6.0";
const BODY = `- New lane drawing workflow: draw road boundary, draw lane dividers, generate lanes automatically
- Matches HOPE device lane configuration UX
- Scanline section generation with edge-snapping dividers
- Click generated sections to assign as lanes
- Existing zone drawing (virtual lines, detection zones, etc.) unchanged`;

const ASSETS = [
  "dist/HOPE-Review-Setup-1.6.0.exe",
  "dist/HOPE-Review-Setup-1.6.0.exe.blockmap",
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
