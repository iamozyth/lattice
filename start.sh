#!/bin/sh
set -e

echo "[lattice] Running database migrations"
LATTICE_NO_SCHEDULER=1 flask db upgrade

# One worker: the scheduler and scan jobs live in this process
echo "[lattice] Starting server"
exec gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 8 --timeout 120 \
    --access-logfile - --error-logfile - wsgi:app
