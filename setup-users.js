const { Pool } = require("pg");
const bcrypt = require("bcryptjs");
require("dotenv").config();

const p = new Pool({
  host: process.env.PGHOST,
  port: parseInt(process.env.PGPORT || "5432", 10),
  database: process.env.PGDATABASE,
  user: process.env.PGUSER,
  password: process.env.PGPASSWORD,
  ssl: process.env.PGSSL === "true" ? { rejectUnauthorized: false } : false,
});

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

  // Seed default users
  const users = [
    {
      username: "admin",
      password: "admin123",
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
      password: "williams123",
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
      password: "james123",
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

  for (const u of users) {
    const existing = await p.query("SELECT id FROM users WHERE username = $1", [u.username]);
    if (existing.rows.length > 0) {
      console.log(`  ${u.username} already exists, skipping`);
      continue;
    }
    const hash = await bcrypt.hash(u.password, 12);
    await p.query(
      `INSERT INTO users (username, password, display_name, role, privileges)
       VALUES ($1, $2, $3, $4, $5)`,
      [u.username, hash, u.display_name, u.role, JSON.stringify(u.privileges)]
    );
    console.log(`  ${u.username} created (${u.role})`);
  }

  const { rows } = await p.query("SELECT id, username, display_name, role FROM users ORDER BY id");
  console.log("\nAll users:");
  rows.forEach((r) => console.log(`  [${r.id}] ${r.username} — ${r.display_name} (${r.role})`));

  await p.end();
}

run().catch((e) => { console.error("ERROR:", e.message); p.end(); });
