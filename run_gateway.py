"""Start the review gateway against the online Postgres.

Reads the connection details from the pre-gateway env file and builds
GWREV_DB_URL in-process, so the password is never typed on a command line, put
in shell history, or echoed to a log.

    python run_gateway.py                 # online Postgres (sovaliushope_gw)
    python run_gateway.py --db sovaliushope_gw

The gateway is the only thing that talks to the database. The desktop app
authenticates to it over localhost and never holds a database credential --
that separation is the whole point of the C-2 rewrite (commit a2845d0) and of
the credential incident that preceded it.
"""
from __future__ import annotations

import argparse
import io
import os

SRC_ENV = ".env.pre-gateway.DO-NOT-COMMIT"


def load_env(path=SRC_ENV):
    env = {}
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sovaliushope_gw",
                    help="database name (default: the gateway's own DB)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args()

    env = load_env()
    os.environ["GWREV_DB_URL"] = (
        "postgresql+psycopg2://%s:%s@%s:%s/%s?sslmode=require"
        % (env["PGUSER"], env["PGPASSWORD"], env["PGHOST"], env["PGPORT"], args.db)
    )
    os.environ.setdefault("GWREV_ENV", "prod")
    # Evidence lives in S3 for this deployment; the gateway presigns it
    # server-side so the desktop app never needs AWS credentials.
    if env.get("S3_BUCKET"):
        os.environ.setdefault("GWREV_EVIDENCE_STORE", "s3")
        os.environ.setdefault("GWREV_S3_BUCKET", env["S3_BUCKET"])
        os.environ.setdefault("GWREV_S3_REGION", env.get("AWS_REGION", "us-east-1"))
        os.environ.setdefault("AWS_ACCESS_KEY_ID", env.get("AWS_ACCESS_KEY_ID", ""))
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", env.get("AWS_SECRET_ACCESS_KEY", ""))

    print("gateway -> %s@%s/%s" % (env["PGUSER"], env["PGHOST"].split(".")[0], args.db))
    print("evidence -> %s" % os.environ.get("GWREV_EVIDENCE_STORE", "local"))
    print("listening on http://%s:%d" % (args.host, args.port))

    import uvicorn
    from gateway.main import app

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
