"""docrunner_project/wsgi.py — WSGI entrypoint for gunicorn."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docrunner_project.settings")
application = get_wsgi_application()
