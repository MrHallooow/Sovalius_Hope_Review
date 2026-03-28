-- H.O.P.E. Review Database Schema
-- Run once against your PostgreSQL database:
--   psql -h localhost -U postgres -d hope -f schema.sql

CREATE TABLE IF NOT EXISTS violations (
  id            TEXT PRIMARY KEY,
  type          TEXT NOT NULL,
  speed         INTEGER,
  speed_limit   INTEGER,
  plate         TEXT,
  vehicle       TEXT,
  location      TEXT,
  gps_lat       DOUBLE PRECISION,
  gps_lng       DOUBLE PRECISION,
  cameras       TEXT[],
  camera        TEXT,
  date          TIMESTAMPTZ NOT NULL,
  confidence    DOUBLE PRECISION,
  weather       TEXT,
  ai_summary    TEXT,
  status        TEXT NOT NULL DEFAULT 'pending',
  reviewed_by   TEXT,
  reviewed_at   TIMESTAMPTZ,
  notes         TEXT DEFAULT '',
  pinned        BOOLEAN DEFAULT FALSE,
  history       JSONB DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS cameras (
  id          TEXT PRIMARY KEY,
  location    TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'online',
  last_ping   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
  id            SERIAL PRIMARY KEY,
  officer       TEXT NOT NULL,
  action        TEXT NOT NULL,
  violation_id  TEXT REFERENCES violations(id),
  at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS notifications (
  id    SERIAL PRIMARY KEY,
  type  TEXT NOT NULL,
  msg   TEXT NOT NULL,
  at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  read  BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_violations_status ON violations(status);
CREATE INDEX IF NOT EXISTS idx_violations_date   ON violations(date DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_at      ON audit_log(at DESC);
