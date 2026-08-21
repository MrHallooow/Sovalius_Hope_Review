#!/usr/bin/env node
/**
 * Smoke test: drives electron/gatewayClient.js against a LOCALLY running
 * review gateway (http://127.0.0.1:8090 by default) end to end:
 *
 *   ready -> login (seeded admin) -> violations -> PATCH review (pinned
 *   toggle, restored) -> audit log -> camera lanes -> evidence URLs ->
 *   prefs round-trip (restored)
 *
 * Prints PASS/FAIL per step. Exit codes: 0 all pass, 1 step failed,
 * 2 gateway not reachable (start it first:
 *   cd gateway && python -m uvicorn gateway.main:app --port 8090
 * with GWREV_SEED=1 GWREV_SEED_PASSWORD=<pw> on first run).
 *
 * Credentials: SMOKE_USERNAME (default "admin") + SMOKE_PASSWORD (falls back
 * to GWREV_SEED_PASSWORD). Never hardcoded here.
 */

import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const gateway = require(path.join(__dirname, "..", "electron", "gatewayClient.js"));

// ── config ──────────────────────────────────────────────────────────────
function gatewayUrlFromDotenv() {
  try {
    const text = readFileSync(path.join(__dirname, "..", ".env"), "utf8");
    const m = text.match(/^\s*GATEWAY_URL\s*=\s*(.+?)\s*$/m);
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

const GATEWAY_URL = process.env.GATEWAY_URL || gatewayUrlFromDotenv() || "http://127.0.0.1:8090";
const USERNAME = process.env.SMOKE_USERNAME || "admin";
const PASSWORD = process.env.SMOKE_PASSWORD || process.env.GWREV_SEED_PASSWORD || "";

gateway.init(GATEWAY_URL);

// ── tiny harness ────────────────────────────────────────────────────────
let failures = 0;
function report(name, ok, detail = "") {
  const tag = ok ? "PASS" : "FAIL";
  if (!ok) failures += 1;
  console.log(`[${tag}] ${name}${detail ? ` — ${detail}` : ""}`);
  return ok;
}

async function step(name, fn) {
  try {
    const detail = await fn();
    return report(name, true, typeof detail === "string" ? detail : "");
  } catch (err) {
    return report(name, false, err.message);
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

// ── steps ───────────────────────────────────────────────────────────────
async function main() {
  console.log(`smoke_gateway: target ${GATEWAY_URL}`);

  // 0. Reachability gate — do not run the suite against a downed gateway.
  const ready = await gateway.testConnection();
  if (!ready.ok) {
    console.log(`[SKIP] gateway not up at ${GATEWAY_URL} (${ready.error})`);
    console.log("       start it, then re-run: npm run smoke:gateway");
    process.exit(2);
  }
  report("ready probe (/ready)", true);

  if (!PASSWORD) {
    console.log("[FAIL] no password: set SMOKE_PASSWORD (or GWREV_SEED_PASSWORD)");
    process.exit(1);
  }

  // 1. Login as the seeded admin (tokens stay inside gatewayClient).
  const okLogin = await step(`login as '${USERNAME}'`, async () => {
    const r = await gateway.login(USERNAME, PASSWORD);
    assert(r.ok, r.error || "login refused");
    assert(r.user && r.user.role, "no user in login response");
    assert(!("accessToken" in r), "tokens must NOT leak out of the client surface");
    return `role=${r.user.role}`;
  });
  if (!okLogin) process.exit(1); // everything below needs the token

  // 2. Violations, in the LEGACY renderer row shape.
  let firstViolation = null;
  await step("GET violations (legacy row shape)", async () => {
    const r = await gateway.getViolations();
    assert(r.ok, r.error);
    assert(Array.isArray(r.rows) && r.rows.length > 0, "no violation rows (seed the dev DB)");
    const row = r.rows[0];
    for (const k of ["violation_type", "timestamp", "license_plate", "extra_data", "review_status",
                     // enforcement gate — the desk must be able to SHOW it
                     "citable", "gateReason"]) {
      assert(k in row, `legacy field '${k}' missing from violation row`);
    }
    firstViolation = row;
    return `${r.rows.length} rows, first=${row.id}`;
  });

  // 3. PATCH a review: toggle pinned, then restore (leaves data as found;
  //    both writes land server-side audit rows).
  await step("PATCH review (pinned toggle + restore)", async () => {
    assert(firstViolation, "no violation to review");
    const id = firstViolation.id;
    const wasPinned = !!firstViolation.review_pinned;
    const r1 = await gateway.updateViolationReview(id, { pinned: !wasPinned });
    assert(r1.ok, r1.error);
    assert(r1.row && !!r1.row.pinned === !wasPinned, "pinned not applied");
    const r2 = await gateway.updateViolationReview(id, { pinned: wasPinned });
    assert(r2.ok, r2.error);
    return `violation=${id}`;
  });

  // 4. Audit log shows the SERVER-written pin rows.
  await step("GET audit log (server-side rows)", async () => {
    const r = await gateway.getAuditLog();
    assert(r.ok, r.error);
    assert(Array.isArray(r.rows) && r.rows.length > 0, "no audit rows");
    const pinRow = r.rows.find(
      (a) => (a.action === "pinned" || a.action === "unpinned") && a.officer === USERNAME
    );
    assert(pinRow, "pin toggle did not produce an audit row");
    assert(pinRow.id && pinRow.at, "audit row missing id/at");
    return `${r.rows.length} rows, latest=${r.rows[0].action}`;
  });

  // 5. Camera lanes for the seeded calibration.
  await step("GET camera lanes (CAM-AV-07)", async () => {
    const r = await gateway.getCameraLanes("CAM-AV-07");
    assert(r.ok, r.error);
    assert(r.data, "no lane data for CAM-AV-07 (seed the dev DB)");
    for (const k of ["lane_data", "calibration_width", "calibration_height"]) {
      assert(k in r.data, `legacy lanes field '${k}' missing`);
    }
    return `calibration ${r.data.calibration_width}x${r.data.calibration_height}`;
  });

  // 5b. All-lanes listing (db:get-all-camera-lanes surface).
  await step("GET all camera lanes", async () => {
    const r = await gateway.getAllCameraLanes();
    assert(r.ok, r.error);
    assert(Array.isArray(r.rows) && r.rows.length > 0, "no lane rows");
    assert("camera_name" in r.rows[0], "legacy 'camera_name' missing");
    return `${r.rows.length} rows`;
  });

  // 6. Evidence presigned URLs — CASE-BOUND: asked for by violation id, never
  //    by object key. Presign needs no object to exist (S3 semantics); the URL
  //    must be absolute so <video>/<img> can load it.
  await step("GET case evidence URLs (case-bound, absolute)", async () => {
    assert(firstViolation, "no violation to fetch evidence for");
    const r = await gateway.getEvidenceUrls(firstViolation.id);
    assert(r.ok, r.error);
    for (const k of ["clipUrl", "rawUrl", "screenshotUrl", "tracksUrl"]) {
      assert(k in r, `evidence field '${k}' missing`);
      assert(
        r[k] === null || /^https?:\/\//.test(r[k]),
        `${k} not absolute: ${String(r[k]).slice(0, 40)}`
      );
    }
    return "case evidence presigned";
  });

  // 6b. A key can no longer be smuggled in, and an unknown case 404s.
  await step("evidence for an unknown case is refused", async () => {
    const r = await gateway.getEvidenceUrls("VIO-DOES-NOT-EXIST-SMOKE");
    assert(!r.ok, "unknown case must not mint evidence URLs");
    return `refused: ${r.error}`;
  });

  // 7. Prefs round-trip against the token user's own row, then restore.
  await step("prefs round-trip (write, verify, restore)", async () => {
    const before = await gateway.loadPrefs();
    assert(before.ok, before.error);
    const marker = `smoke-${Date.now()}`;
    const w = await gateway.savePrefs(
      { ...before.preferences, smokeMarker: marker },
      before.keybinds,
      before.theme
    );
    assert(w.ok, w.error);
    const after = await gateway.loadPrefs();
    assert(after.ok, after.error);
    assert(after.preferences.smokeMarker === marker, "marker did not round-trip");
    const restore = await gateway.savePrefs(before.preferences, before.keybinds, before.theme);
    assert(restore.ok, restore.error);
    const final = await gateway.loadPrefs();
    assert(final.ok && !("smokeMarker" in (final.preferences || {})), "prefs not restored");
    return `theme=${before.theme}`;
  });

  console.log(failures === 0 ? "\nsmoke_gateway: ALL PASS" : `\nsmoke_gateway: ${failures} FAILURE(S)`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((err) => {
  console.error("[FAIL] unhandled:", err);
  process.exit(1);
});
