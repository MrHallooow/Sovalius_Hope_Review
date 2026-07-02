"""H.O.P.E. Review Gateway — FastAPI backend for the Electron review app.

Mechanisms lifted from the proven sovalius-dispatch officer gateway (JWT +
refresh rotation, login throttle, tamper-evident audit chain) and adapted to
the review-desk role/privilege model. Dev runs on SQLite + a local-disk
evidence store; port 8090 (8088 belongs to the dispatch gateway).
"""
