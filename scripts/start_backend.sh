#!/bin/sh
# ---------------------------------------------------------------------------
# Backend entrypoint.
#
# 1. wait for PostgreSQL
# 2. apply the database migrations
# 3. start the API (which then starts the trading engine in PAPER mode)
# ---------------------------------------------------------------------------
set -e

cd /app

echo "Waiting for the database..."
python - <<'PYTHON'
import os
import time

import psycopg2

url = os.getenv("DATABASE_URL", "")
dsn = url.replace("postgresql+psycopg2://", "postgresql://")
if not dsn.startswith("postgresql://"):
    print("Not a PostgreSQL database, skipping the wait.")
    raise SystemExit(0)

for attempt in range(60):
    try:
        psycopg2.connect(dsn).close()
        print("Database is ready.")
        break
    except Exception as exc:  # noqa: BLE001
        print(f"Database not ready yet ({attempt + 1}/60): {exc}")
        time.sleep(2)
else:
    raise SystemExit("Database did not become ready in time")
PYTHON

echo "Applying database migrations..."
alembic upgrade head || echo "Alembic failed; the application will create the tables itself."

echo "Starting the API on port 8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
