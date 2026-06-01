"""docrunner_project/urls.py — project root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),  # login/logout (magic-link layered on later)
    path("", include("docrunner.urls")),
]

# Serve generated files from the data volume. In production these are also
# reachable via the authenticated /api/runs/<id>/output download endpoint;
# this MEDIA route is convenient for local/dev and small deployments.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
