#!/bin/bash

set -e

echo "[INFO] Lattice - Starting application..."

# Run database migrations
echo "[INFO] Running database migrations..."
flask db upgrade

echo "[INFO] Migrations completed successfully"
echo "[INFO] Starting Gunicorn server..."

# Start Gunicorn with proper configuration
exec gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 30 --access-logfile - --error-logfile - wsgi:app
