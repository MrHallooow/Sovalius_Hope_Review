"""One-shot: build the gateway schema in a NEW database and copy the live data in.

Why this exists
---------------
v1.6.2 and earlier talked to Postgres directly and read the device-sync column
names off ``violations`` (violation_type / speed_mph / license_plate /
timestamp). Commit a2845d0 (2026-07-04) moved the desktop app behind the review
gateway, which owns an Alembic-managed schema using different names (type /
speed / plate / date), plus tables the old DB never had (refresh_tokens,
decision_outbox, notification_reads) and a hash-chained audit_log.

The two schemas cannot share a database: the gateway's initial migration is all
``op.create_table`` and would collide with the existing tables. So the gateway
gets its OWN database on the same server, and the data is copied across.

NOTHING in the source database is modified -- it is opened READ ONLY. The old
app keeps working throughout, and rollback is one env var (GWREV_DB_URL).

Usage:  python migrate_to_gateway_db.py [--target sovaliushope_gw] [--force]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

SRC_ENV = ".env.pre-gateway.DO-NOT-COMMIT"


def load_env(path=SRC_ENV):
    env = {}
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def connect(env, dbname, readonly=False, autocommit=False):
    c = psycopg2.connect(
        host=env["PGHOST"],
        port=env["PGPORT"],
        dbname=dbname,
        user=env["PGUSER"],
        password=env["PGPASSWORD"],
        sslmode="require",
        connect_timeout=20,
    )
    c.set_session(readonly=readonly, autocommit=autocommit)
    return c


def vid(n):
    """Old violations.id is an integer; the gateway keys violations by string.

    One stable transform, used for violations AND their reviews so the join
    survives the copy.
    """
    return "VIO-%06d" % int(n)


def jget(blob, *keys, **kw):
    default = kw.get("default")
    if not isinstance(blob, dict):
        return default
    for k in keys:
        if k in blob and blob[k] is not None:
            return blob[k]
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="sovaliushope_gw")
    ap.add_argument("--force", action="store_true",
                    help="drop and rebuild the target database")
    args = ap.parse_args()

    env = load_env()
    target = args.target
    print("source : %s (READ ONLY)" % env["PGDATABASE"])
    print("target : %s" % target)

    # ---- 1. create the target database -------------------------------------
    admin = connect(env, env["PGDATABASE"], autocommit=True)
    acur = admin.cursor()
    acur.execute("select 1 from pg_database where datname=%s", (target,))
    exists = acur.fetchone() is not None
    if exists and args.force:
        print("  dropping existing %s (--force)" % target)
        acur.execute('drop database "%s"' % target)
        exists = False
    if not exists:
        acur.execute('create database "%s"' % target)
        print("  created database %s" % target)
    else:
        print("  reusing existing %s" % target)
    admin.close()

    url = "postgresql://%s:%s@%s:%s/%s?sslmode=require" % (
        env["PGUSER"], env["PGPASSWORD"], env["PGHOST"], env["PGPORT"], target)

    # ---- 2. build the gateway schema via Alembic ----------------------------
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path("gateway/migrations").resolve()))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    print("  gateway schema built (alembic head)")

    # ---- 3. copy ------------------------------------------------------------
    src = connect(env, env["PGDATABASE"], readonly=True, autocommit=True)
    dst = connect(env, target)
    s = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    d = dst.cursor()

    # users: column-for-column identical. bcrypt hashes are copied verbatim so
    # every existing password keeps working exactly as before.
    s.execute("select * from users order by id")
    users = s.fetchall()
    for u in users:
        d.execute(
            "insert into users (id,username,password,display_name,role,privileges,"
            "active,preferences,keybinds,theme,created_at,last_login) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (id) do nothing",
            (u["id"], u["username"], u["password"], u["display_name"], u["role"],
             json.dumps(u["privileges"] or {}), u["active"],
             json.dumps(u["preferences"] or {}), json.dumps(u["keybinds"] or {}),
             u["theme"] or "dark", u["created_at"], u["last_login"]))
    d.execute("select setval(pg_get_serial_sequence('users','id'), "
              "(select coalesce(max(id),1) from users))")
    print("  users              %4d" % len(users))

    # violations: the actual column translation.
    s.execute("select * from violations order by id")
    rows = s.fetchall()
    for v in rows:
        coords = v["coordinates"] if isinstance(v["coordinates"], dict) else {}
        extra = v["extra_data"] if isinstance(v["extra_data"], dict) else {}
        speed = v["speed_mph"]
        d.execute(
            "insert into violations (id,type,speed,speed_limit,plate,vehicle,location,"
            "gps_lat,gps_lng,cameras,camera,date,confidence,weather,ai_summary,"
            "status,reviewed_by,reviewed_at,notes,pinned,history,"
            "clip_url,raw_clip_url,screenshot_url,citable,gate_reason) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (id) do nothing",
            (vid(v["id"]),
             v["violation_type"] or "Unknown",
             int(round(speed)) if speed is not None else None,
             jget(extra, "speed_limit"),
             v["license_plate"] or "",
             v["vehicle_class"] or "",
             v["location"] or "",
             jget(coords, "lat", "latitude"),
             jget(coords, "lng", "longitude"),
             json.dumps([v["feed_name"]] if v["feed_name"] else []),
             v["feed_name"] or "",
             v["timestamp"],
             v["confidence"],
             jget(extra, "weather", default="") or "",
             jget(extra, "ai_summary", "pattern", default="") or "",
             "pending", None, None, "", False, json.dumps([]),
             v["remote_clip_url"] or "",
             v["remote_raw_clip_url"] or "",
             v["remote_screenshot_url"] or "",
             # Citation eligibility was never determined for this data -- the
             # enforcement gate postdates it. NULL means "undetermined", which
             # the desk shows as "no citation is minted until the gate
             # confirms" rather than implying one follows.
             None, ""))
    print("  violations         %4d" % len(rows))

    # reviews: newest per violation wins (the old table allowed several rows
    # per violation; the gateway keys the review BY violation).
    s.execute("select distinct on (violation_id) * from violation_reviews "
              "order by violation_id, reviewed_at desc nulls last, id desc")
    reviews = s.fetchall()
    kept = 0
    orphans = 0
    for r in reviews:
        d.execute("select 1 from violations where id=%s", (vid(r["violation_id"]),))
        if d.fetchone() is None:
            orphans += 1
            continue
        d.execute(
            "insert into violation_reviews "
            "(violation_id,status,reviewed_by,reviewed_at,notes,pinned,history) "
            "values (%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (violation_id) do nothing",
            (vid(r["violation_id"]), r["status"] or "pending", r["reviewed_by"],
             r["reviewed_at"], r["notes"] or "", bool(r["pinned"]),
             json.dumps(r["history"] or [])))
        kept += 1
    print("  violation_reviews  %4d%s" % (
        kept, ("  (%d orphaned, skipped)" % orphans) if orphans else ""))

    # Best-effort extras -- these drive the System Status / Feeds screens. Any
    # shape mismatch is reported and skipped, never fatal: the review desk
    # works without them.
    for table, cols in (
        ("cameras", ("id", "location", "status", "last_ping")),
        ("notifications", ("id", "type", "msg", "at", "read")),
    ):
        try:
            s.execute("select * from %s" % table)
            got = s.fetchall()
            n = 0
            for row in got:
                missing = [c for c in cols if c not in row]
                if missing:
                    raise KeyError("missing %s" % ",".join(missing))
                d.execute(
                    "insert into %s (%s) values (%s) on conflict do nothing"
                    % (table, ",".join(cols), ",".join(["%s"] * len(cols))),
                    tuple(row[c] for c in cols))
                n += 1
            print("  %-18s %4d" % (table, n))
        except Exception as e:
            dst.rollback()
            print("  %-18s    - skipped (%s: %s)"
                  % (table, type(e).__name__, str(e).strip()[:60]))

    dst.commit()

    # ---- 4. verify ----------------------------------------------------------
    print("")
    for t in ("users", "violations", "violation_reviews"):
        d.execute("select count(*) from %s" % t)
        print("  verify %-18s %4d rows in target" % (t, d.fetchone()[0]))
    src.close()
    dst.close()

    print("")
    print("Done. Point the gateway at the new database:")
    print('  $env:GWREV_DB_URL = "postgresql://%s:<password>@%s:%s/%s?sslmode=require"'
          % (env["PGUSER"], env["PGHOST"], env["PGPORT"], target))
    print("  python -m gateway.main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
