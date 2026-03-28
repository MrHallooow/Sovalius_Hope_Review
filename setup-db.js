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
  // Check existing tables
  const t = await p.query(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
  );
  console.log("Existing tables:", t.rows.map((r) => r.table_name));

  // Drop and recreate cleanly
  await p.query("DROP TABLE IF EXISTS audit_log CASCADE");
  await p.query("DROP TABLE IF EXISTS notifications CASCADE");
  await p.query("DROP TABLE IF EXISTS cameras CASCADE");
  await p.query("DROP TABLE IF EXISTS violations CASCADE");
  console.log("Dropped old tables");

  await p.query(`CREATE TABLE violations (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, speed INTEGER, speed_limit INTEGER,
    plate TEXT, vehicle TEXT, location TEXT, gps_lat DOUBLE PRECISION, gps_lng DOUBLE PRECISION,
    cameras TEXT[], camera TEXT, date TIMESTAMPTZ NOT NULL, confidence DOUBLE PRECISION,
    weather TEXT, ai_summary TEXT, status TEXT NOT NULL DEFAULT 'pending',
    reviewed_by TEXT, reviewed_at TIMESTAMPTZ, notes TEXT DEFAULT '',
    pinned BOOLEAN DEFAULT FALSE, history JSONB DEFAULT '[]'::jsonb
  )`);
  console.log("violations OK");

  await p.query(`CREATE TABLE cameras (
    id TEXT PRIMARY KEY, location TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'online', last_ping TIMESTAMPTZ
  )`);
  console.log("cameras OK");

  await p.query(`CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY, officer TEXT NOT NULL, action TEXT NOT NULL,
    violation_id TEXT REFERENCES violations(id),
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(), notes TEXT DEFAULT ''
  )`);
  console.log("audit_log OK");

  await p.query(`CREATE TABLE notifications (
    id SERIAL PRIMARY KEY, type TEXT NOT NULL, msg TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(), read BOOLEAN DEFAULT FALSE
  )`);
  console.log("notifications OK");

  await p.query("CREATE INDEX idx_violations_status ON violations(status)");
  await p.query("CREATE INDEX idx_violations_date ON violations(date DESC)");
  await p.query("CREATE INDEX idx_audit_log_at ON audit_log(at DESC)");
  console.log("indexes OK");

  // Seed cameras
  await p.query(`INSERT INTO cameras (id, location, status, last_ping) VALUES
    ('CAM-AV-07','Leeward Hwy, Arnos Vale','online',NOW()-interval '30 seconds'),
    ('CAM-KT-12','Bay Street, Kingstown','online',NOW()-interval '15 seconds'),
    ('CAM-KT-03','Halifax St, Kingstown','online',NOW()-interval '45 seconds'),
    ('CAM-CQ-02','Windward Hwy, Calliaqua','offline',NOW()-interval '1 hour'),
    ('CAM-QS-01','Leeward Hwy, Questelles','online',NOW()-interval '20 seconds'),
    ('CAM-KT-08','Vigie Highway, Kingstown','online',NOW()-interval '60 seconds'),
    ('CAM-KT-15','Kingstown Bypass','degraded',NOW()-interval '2 minutes')
  `);
  console.log("cameras seeded");

  // Seed violations
  await p.query(`INSERT INTO violations (id,type,speed,speed_limit,plate,vehicle,location,gps_lat,gps_lng,cameras,camera,date,confidence,weather,ai_summary,status,reviewed_by,reviewed_at,notes,pinned,history) VALUES
    ('VIO-2026-00147','Speeding',78,50,'SV-4829','Silver Toyota Corolla','Leeward Highway, Arnos Vale',13.1339,-61.2108,ARRAY['CAM-AV-07','CAM-AV-08'],'CAM-AV-07','2026-03-20T09:34:12Z',94.7,'Clear','Vehicle at 78 km/h in 50 zone. Plate SV-4829 at 98.2%.','pending',NULL,NULL,'',false,'[{"action":"flagged","by":"AI System","at":"2026-03-20T09:34:12","notes":"Auto-detected by YOLO pipeline"}]'::jsonb),
    ('VIO-2026-00146','Reckless Driving',NULL,NULL,'SV-7103','Red Nissan March','Bay Street, Kingstown',13.1553,-61.2275,ARRAY['CAM-KT-12'],'CAM-KT-12','2026-03-20T09:21:45Z',87.3,'Overcast','Dangerous overtaking across double yellow lines.','pending',NULL,NULL,'',false,'[{"action":"flagged","by":"AI System","at":"2026-03-20T09:21:45","notes":"Auto-detected"}]'::jsonb),
    ('VIO-2026-00145','Illegal Parking',NULL,NULL,'SV-2256','White Hyundai Tucson','Halifax St, Kingstown',13.1567,-61.2258,ARRAY['CAM-KT-03','CAM-KT-04'],'CAM-KT-03','2026-03-20T08:55:30Z',96.1,'Clear','No-parking zone 12+ min. Plate at 99.1%.','pending',NULL,NULL,'',false,'[{"action":"flagged","by":"AI System","at":"2026-03-20T08:55:30","notes":"Auto-detected"}]'::jsonb),
    ('VIO-2026-00144','Speeding',65,40,'SV-9481','Blue Honda Fit','Windward Highway, Calliaqua',13.1412,-61.1953,ARRAY['CAM-CQ-02'],'CAM-CQ-02','2026-03-20T08:42:18Z',91.2,'Rain','65 km/h in 40 school zone. Wet road.','pending',NULL,NULL,'',false,'[{"action":"flagged","by":"AI System","at":"2026-03-20T08:42:18","notes":"School zone active"}]'::jsonb),
    ('VIO-2026-00143','Speeding',72,50,'SV-4829','Silver Toyota Corolla','Leeward Highway, Questelles',13.1721,-61.2489,ARRAY['CAM-QS-01'],'CAM-QS-01','2026-03-20T08:15:03Z',89.8,'Clear','72 km/h in 50 zone. Same plate as VIO-147.','approved','Sgt. Williams',NOW()-interval '1 hour','Clear violation.',false,'[{"action":"flagged","by":"AI System","at":"2026-03-20T08:15:03","notes":""},{"action":"viewed","by":"Sgt. Williams","at":"2026-03-20T08:30:00","notes":""},{"action":"approved","by":"Sgt. Williams","at":"2026-03-20T09:00:00","notes":"Clear violation."}]'::jsonb),
    ('VIO-2026-00142','Reckless Driving',NULL,NULL,'SV-6640','Grey Suzuki Swift','Vigie Highway, Kingstown',13.1601,-61.2312,ARRAY['CAM-KT-08'],'CAM-KT-08','2026-03-20T07:58:22Z',73.4,'Dawn','Sharp U-turn. Low light.','dismissed','Cpl. James',NOW()-interval '2 hours','Low confidence.',false,'[{"action":"flagged","by":"AI System","at":"2026-03-20T07:58:22","notes":""},{"action":"viewed","by":"Cpl. James","at":"2026-03-20T08:10:00","notes":""},{"action":"dismissed","by":"Cpl. James","at":"2026-03-20T08:30:00","notes":"Low confidence."}]'::jsonb),
    ('VIO-2026-00141','Speeding',68,50,'SV-1192','White Toyota Hiace','Kingstown Bypass',13.158,-61.23,ARRAY['CAM-KT-15'],'CAM-KT-15','2026-03-20T07:30:00Z',92.5,'Clear','68 km/h in 50 zone.','approved','Sgt. Williams',NOW()-interval '90 minutes','Clear speeding.',false,'[{"action":"flagged","by":"AI System","at":"2026-03-20T07:30:00","notes":""},{"action":"approved","by":"Sgt. Williams","at":"2026-03-20T08:00:00","notes":"Clear speeding."}]'::jsonb)
  `);
  console.log("violations seeded");

  // Seed audit log
  await p.query(`INSERT INTO audit_log (officer, action, violation_id, at, notes) VALUES
    ('Sgt. Williams','approved','VIO-2026-00143',NOW()-interval '1 hour','Clear violation.'),
    ('Cpl. James','dismissed','VIO-2026-00142',NOW()-interval '2 hours','Low confidence.'),
    ('Sgt. Williams','approved','VIO-2026-00141',NOW()-interval '90 minutes','Clear speeding.'),
    ('Sgt. Williams','viewed','VIO-2026-00143',NOW()-interval '70 minutes',''),
    ('Cpl. James','viewed','VIO-2026-00142',NOW()-interval '125 minutes',''),
    ('System','flagged','VIO-2026-00147','2026-03-20T09:34:12Z','AI auto-detection')
  `);
  console.log("audit_log seeded");

  // Seed notifications
  await p.query(`INSERT INTO notifications (type, msg, at, read) VALUES
    ('violation','New violation VIO-2026-00147 flagged',NOW()-interval '1 minute',false),
    ('system','CAM-CQ-02 went offline',NOW()-interval '1 hour',false),
    ('override','Supervisor reviewed VIO-2026-00143',NOW()-interval '2 hours',true)
  `);
  console.log("notifications seeded");

  // Verify
  const vc = await p.query("SELECT count(*) FROM violations");
  const cc = await p.query("SELECT count(*) FROM cameras");
  const ac = await p.query("SELECT count(*) FROM audit_log");
  console.log(`\nDone! violations:${vc.rows[0].count} cameras:${cc.rows[0].count} audit:${ac.rows[0].count}`);

  await p.end();
}

run().catch((e) => { console.error("ERROR:", e.message); p.end(); });
