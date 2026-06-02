#!/usr/bin/env bash
# DocRunner entrypoint.
set -euo pipefail

# Ensure SECRET_KEY is always set — django-q reads it at import time.
# Coolify injects the real value via environment variables; this fallback
# is only used if the env var didn't arrive (should not happen in production).
export SECRET_KEY="${SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(50))')}"
export ENCRYPTION_KEY="${ENCRYPTION_KEY:-}"
export DEBUG="${DEBUG:-False}"
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-localhost,127.0.0.1,docrunner.owncpanel.online}"
export CSRF_TRUSTED_ORIGINS="${CSRF_TRUSTED_ORIGINS:-}"
export DATA_DIR="${DATA_DIR:-/app/data}"
export TIME_ZONE="${TIME_ZONE:-UTC}"
export Q_WORKERS="${Q_WORKERS:-2}"
export WEB_WORKERS="${WEB_WORKERS:-3}"

echo "[entrypoint] SECRET_KEY is set: $([ -n "$SECRET_KEY" ] && echo yes || echo NO)"
echo "[entrypoint] ENCRYPTION_KEY is set: $([ -n "$ENCRYPTION_KEY" ] && echo yes || echo NO)"

echo "[entrypoint] Applying migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] Starting q-cluster worker..."
python manage.py qcluster &
QCLUSTER_PID=$!

trap 'echo "[entrypoint] shutting down..."; kill $QCLUSTER_PID 2>/dev/null || true' EXIT TERM INT

echo "[entrypoint] Starting web server on :8000..."
exec gunicorn docrunner_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${WEB_WORKERS}" \
    --timeout 120
