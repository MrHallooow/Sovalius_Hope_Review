"""Uvicorn entrypoint (port 8090 — 8088 belongs to the dispatch gateway).

    python -m uvicorn gateway.main:app --host 127.0.0.1 --port 8090

Or run this file directly: ``python -m gateway.main``.
"""

from __future__ import annotations

from .app import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Bind loopback only: the Electron main process on the same machine is the
    # sole caller in dev.
    uvicorn.run(app, host="127.0.0.1", port=8090)
