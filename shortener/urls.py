from django.urls import path

from .views import shorten_url, url_stats


urlpatterns = [
    path("shorten/", shorten_url, name="shorten-url"),
    path("urls/<str:code>/", url_stats, name="url-stats"),
]