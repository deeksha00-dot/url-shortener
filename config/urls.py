from django.contrib import admin
from django.urls import include, path

from shortener.views import redirect_url


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("shortener.urls")),
    path("<str:code>/", redirect_url, name="redirect-url"),
]