"""docrunner/urls.py — owner UI, JSON API, and the public webhook endpoint."""
from django.urls import path

from docrunner import views

urlpatterns = [
    # Templates
    path("", views.template_list, name="template_list"),
    path("templates/upload/", views.template_upload, name="template_upload"),
    path("templates/<uuid:template_id>/", views.template_detail, name="template_detail"),

    # On-demand generation (UI forms)
    path("templates/<uuid:template_id>/generate/form/", views.generate_form, name="generate_form"),
    path("templates/<uuid:template_id>/generate/json/", views.generate_json, name="generate_json"),
    path("templates/<uuid:template_id>/generate/csv/", views.generate_csv, name="generate_csv"),

    # Runs
    path("runs/", views.run_list, name="run_list"),
    path("runs/<uuid:run_id>/", views.run_detail, name="run_detail"),

    # JSON API
    path("api/templates/<uuid:template_id>/generate", views.api_generate, name="api_generate"),
    path("api/runs/<uuid:run_id>", views.api_run_status, name="api_run_status"),
    path("api/runs/<uuid:run_id>/output", views.run_output, name="run_output"),

    # Public inbound webhook
    path("hooks/<str:token>", views.webhook_receive, name="webhook_receive"),
]
