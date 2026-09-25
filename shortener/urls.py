from django.urls import path

from .views import (
    delete_url,
    login_view,
    my_urls,
    shorten_url,
    url_stats,
)


urlpatterns = [
    path(
        "login/",
        login_view,
        name="login"
    ),

    path(
        "shorten/",
        shorten_url,
        name="shorten-url"
    ),

    path(
        "my-urls/",
        my_urls,
        name="my-urls"
    ),

    path(
        "urls/<str:code>/",
        url_stats,
        name="url-stats"
    ),

    path(
        "urls/<str:code>/delete/",
        delete_url,
        name="delete-url"
    ),
]