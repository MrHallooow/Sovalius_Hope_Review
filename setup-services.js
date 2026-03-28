const { Pool } = require("pg");
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
  await p.query("DROP TABLE IF EXISTS services CASCADE");

  await p.query(`CREATE TABLE services (
    id       SERIAL PRIMARY KEY,
    name     TEXT UNIQUE NOT NULL,
    status   TEXT NOT NULL DEFAULT 'operational',
    detail   TEXT,
    uptime   TEXT,
    latency  TEXT,
    usage    TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
  )`);
  console.log("services table created");

  await p.query(`INSERT INTO services (name, status, detail, uptime, latency, usage) VALUES
    ('AI Detection Pipeline', 'operational', 'YOLO + DeepStream', '99.97%', '42ms', NULL),
    ('Evidence Storage', 'operational', 'Encrypted NVR cluster', '99.99%', NULL, '2.4 TB / 10 TB'),
    ('Database', 'operational', 'PostgreSQL primary', '99.99%', '3ms', NULL),
    ('Plate Recognition (ANPR)', 'operational', 'OCR engine v3.2', '99.92%', '85ms', NULL),
    ('Network Gateway', 'degraded', 'High latency detected', '98.4%', '210ms', NULL),
    ('Backup System', 'operational', 'Last backup 2h ago', '99.95%', NULL, '1.8 TB')
  `);
  console.log("services seeded");

  const { rows } = await p.query("SELECT name, status, uptime FROM services ORDER BY id");
  rows.forEach((r) => console.log(`  ${r.name}: ${r.status} (${r.uptime})`));

  await p.end();
}

run().catch((e) => { console.error("ERROR:", e.message); p.end(); });
