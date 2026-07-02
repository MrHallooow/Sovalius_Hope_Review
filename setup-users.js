const crypto = require("crypto");
const { Pool } = require("pg");
const bcrypt = require("bcryptjs");
require("dotenv").config();

// Safety gate: this script seeds well-known usernames into the users
// table. Seeding a production database with guessable accounts is how
// systems get owned, so it refuses to run unless explicitly in dev
// (NODE_ENV=development) or forced with --dev.
const isDev =
  process.env.NODE_ENV === "development" || process.argv.includes("--dev");
if (!isDev) {
  console.error(
    "setup-users.js refused to run: seeding default users is a development-" +
      "only operation. Set NODE_ENV=development or pass --dev to override.\n" +
      "Production users must be created individually through the app's " +
      "user-management screen."
  );
  process.exit(1);
}

const p = new Pool({
  host: process.env.PGHOST,
  port: parseInt(process.env.PGPORT || "5432", 10),
  database: process.env.PGDATABASE,
  user: process.env.PGUSER,
  password: process.env.PGPASSWORD,
  ssl: process.env.PGSSL === "true" ? { rejectUnauthorized: false } : false,
});

// One-time random passwords, printed once at the end of the run.
// No more hardcoded admin123-style credentials anywhere on disk.
function oneTimePassword() {
  return crypto.randomBytes(12).toString("base64url");
}

async function run() {
  await p.query(`CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'officer',
    privileges  JSONB NOT NULL DEFAULT '{}'::jsonb,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    last_login  TIMESTAMPTZ
  )`);
  console.log("users table created");

  await p.query("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)");

  // Seed default users (dev only — see gate above).
  const users = [
    {
      username: "admin",
      display_name: "Administrator",
      role: "admin",
      privileges: {
        canApprove: true,
        canDismiss: true,
        canRevise: true,
        canManageUsers: true,
        canManageCameras: true,
        canViewAudit: true,
        canExport: true,
      },
    },
    {
      username: "sgt.williams",
      display_name: "Sgt. Williams",
      role: "supervisor",
      privileges: {
        canApprove: true,
        canDismiss: true,
        canRevise: true,
        canManageUsers: false,
        canManageCameras: true,
        canViewAudit: true,
        canExport: true,
      },
    },
    {
      username: "cpl.james",
      display_name: "Cpl. James",
      role: "officer",
      privileges: {
        canApprove: true,
        canDismiss: true,
        canRevise: false,
        canManageUsers: false,
        canManageCameras: false,
        canViewAudit: false,
        canExport: false,
      },
    },
  ];

  const issued = [];
  for (const u of users) {
    const existing = await p.query("SELECT id FROM users WHERE username = $1", [u.username]);
    if (existing.rows.length > 0) {
      console.log(`  ${u.username} already exists, skipping`);
      continue;
    }
    const password = oneTimePassword();
    const hash = await bcrypt.hash(password, 12);
    await p.query(
      `INSERT INTO users (username, password, display_name, role, privileges)
       VALUES ($1, $2, $3, $4, $5)`,
      [u.username, hash, u.display_name, u.role, JSON.stringify(u.privileges)]
    );
    issued.push({ username: u.username, password });
    console.log(`  ${u.username} created (${u.role})`);
  }

  const { rows } = await p.query("SELECT id, username, display_name, role FROM users ORDER BY id");
  console.log("\nAll users:");
  rows.forEach((r) => console.log(`  [${r.id}] ${r.username} — ${r.display_name} (${r.role})`));

  if (issued.length > 0) {
    console.log(
      "\nOne-time passwords (shown ONCE — store securely, change on first login):"
    );
    issued.forEach((u) => console.log(`  ${u.username}: ${u.password}`));
  }

  await p.end();
}

run().catch((e) => { console.error("ERROR:", e.message); p.end(); });
