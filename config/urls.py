from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from django.views.static import serve

from shortener.views import redirect_url


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("shortener.urls")),

    # Frontend (plain HTML/CSS/JS) served by Django at /app/
    path(
        "app/<path:path>",
        serve,
        {"document_root": settings.FRONTEND_DIR}
    ),

    # Home page -> login/dashboard
    path(
        "",
        RedirectView.as_view(url="/app/login.html"),
        name="home"
    ),

    # Short links: /abc123 (the old /abc123/ form keeps working too)
    path("<str:code>", redirect_url, name="redirect-url"),
    path("<str:code>/", redirect_url),
]
