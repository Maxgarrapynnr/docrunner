#!/usr/bin/env bash
# DocRunner entrypoint. Runs migrations, collects static, then starts BOTH the
# web server and the django-q2 worker in one container (PyRunner's model).
set -euo pipefail

echo "[entrypoint] Applying migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

# Start the django-q2 worker in the background. It runs every generation and
# delivery task; without it, runs would sit QUEUED forever.
echo "[entrypoint] Starting q-cluster worker..."
python manage.py qcluster &
QCLUSTER_PID=$!

# If the worker dies, take the whole container down so the orchestrator restarts
# it cleanly (avoids a half-alive container that accepts work but never runs it).
trap 'echo "[entrypoint] shutting down..."; kill $QCLUSTER_PID 2>/dev/null || true' EXIT TERM INT

echo "[entrypoint] Starting web server on :8000..."
exec gunicorn docrunner_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WEB_WORKERS:-3}" \
    --timeout 120
