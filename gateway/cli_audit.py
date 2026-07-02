"""Audit-chain operator CLI (cron / CI / Windows Task Scheduler friendly).

    python -m gateway.cli_audit verify [--from SEQ] [--json]
    python -m gateway.cli_audit head [--json]

Exit code: 0 when the chain is intact, 1 when verify finds tampering — so a
scheduled task can alert on a non-zero exit.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import audit
from .db import SessionLocal


def _cmd_verify(args) -> int:
    db = SessionLocal()
    try:
        r = audit.verify_chain(db, start_seq=args.from_seq)
    finally:
        db.close()
    if args.json:
        print(json.dumps(r))
    else:
        if r["ok"]:
            print(
                f"OK: audit chain intact — {r['checked']} rows verified, "
                f"head seq={r['head_seq']} hash={r['head_hash']}"
            )
        else:
            print(
                f"FAIL: audit chain BROKEN at seq={r['first_broken_seq']}: {r['reason']} "
                f"({r['checked']} rows verified before the break)"
            )
    return 0 if r["ok"] else 1


def _cmd_head(args) -> int:
    db = SessionLocal()
    try:
        h = audit.head(db)
    finally:
        db.close()
    if args.json:
        print(json.dumps(h))
    else:
        print(f"head seq={h['seq']} hash={h['hash']} count={h['count']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gateway.cli_audit", description="Review-gateway audit chain tools"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser("verify", help="verify the audit hash chain")
    p_verify.add_argument("--from", dest="from_seq", type=int, default=1, help="start seq")
    p_verify.add_argument("--json", action="store_true", help="machine-readable output")
    p_verify.set_defaults(func=_cmd_verify)

    p_head = sub.add_parser("head", help="print current chain head + count")
    p_head.add_argument("--json", action="store_true")
    p_head.set_defaults(func=_cmd_head)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
