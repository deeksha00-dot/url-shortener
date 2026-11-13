import logging
import re

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import Http404, HttpResponseGone
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_safe

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import URL
from .queue import queue_client
from .rate_limit import (
    get_client_ip,
    is_rate_limited,
)
from .serializers import RegisterSerializer, URLCreateSerializer
from .services import create_short_url, record_click


logger = logging.getLogger(__name__)

# Valid short codes: letters, digits, "-" and "_" (max 50, same as the model).
# Anything else cannot exist, so answer 404 without touching Redis or the DB.
CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,50}")


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Report whether the app can reach its database and Redis.

    Redis being down is "degraded", not "down": the app still works
    because it falls back to the database.
    """
    try:
        URL.objects.exists()
        database_ok = True
    except Exception:
        database_ok = False

    try:
        queue_client.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    if not database_ok:
        overall = "down"
    elif not redis_ok:
        overall = "degraded"
    else:
        overall = "ok"

    return Response(
        {
            "status": overall,
            "database": "up" if database_ok else "down",
            "redis": "up" if redis_ok else "down",
        },
        status=(
            status.HTTP_200_OK
            if database_ok
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register_view(request):
    if is_rate_limited(
        "register",
        get_client_ip(request),
        limit=5,
        window_seconds=60
    ):
        return Response(
            {
                "error": (
                    "Too many sign-up attempts. "
                    "Please try again later."
                )
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = RegisterSerializer(
        data=request.data
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    user = User.objects.create_user(
        username=serializer.validated_data["username"],
        password=serializer.validated_data["password"]
    )

    token, _ = Token.objects.get_or_create(
        user=user
    )

    return Response(
        {
            "token": token.key
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login_view(request):
    client_ip = get_client_ip(request)

    if is_rate_limited(
        "login",
        client_ip,
        limit=5,
        window_seconds=60
    ):
        return Response(
            {
                "error": (
                    "Too many login attempts. "
                    "Please try again later."
                )
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    
    username = request.data.get("username")
    password = request.data.get("password")

    user = authenticate(
        username=username,
        password=password
    )

    if user is None:
        return Response(
            {
                "error": "Invalid username or password."
            },
            status=status.HTTP_401_UNAUTHORIZED
        )

    token, _ = Token.objects.get_or_create(
        user=user
    )

    return Response({
        "token": token.key
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def shorten_url(request):
    if is_rate_limited(
        "shorten",
        request.user.id,
        limit=10,
        window_seconds=60
    ):
        return Response(
            {
                "error": (
                    "Too many URL creation requests. "
                    "Please try again later."
                )
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    serializer = URLCreateSerializer(
        data=request.data
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        url = create_short_url(
            serializer.validated_data["url"],
            serializer.validated_data.get("expires_at"),
            serializer.validated_data.get("custom_alias"),
            request.user
        )

    except ValueError as e:
        return Response(
            {
                "error": str(e)
            },
            status=status.HTTP_409_CONFLICT
        )

    except RuntimeError as e:
        return Response(
            {
                "error": str(e)
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    short_url = request.build_absolute_uri(
        f"/{url.code}"
    )

    return Response(
        {
            "short_url": short_url
        },
        status=status.HTTP_201_CREATED
    )


@require_safe
def redirect_url(request, code):
    if not CODE_PATTERN.fullmatch(code):
        raise Http404("Invalid short code.")

    cache_key = f"url:{code}"

    # 1. Check Redis first. If Redis is down, cache.get() returns None
    #    (see IGNORE_EXCEPTIONS in settings), so we simply use the database.
    cached_data = cache.get(cache_key)
    cache_status = "HIT"

    if cached_data is None:
        cache_status = "MISS"

        # 2. Cache miss -> query the database (404 if it does not exist)
        url = get_object_or_404(
            URL,
            code=code
        )

        # 3. Check expiration from database
        if (
            url.expires_at
            and url.expires_at <= timezone.now()
        ):
            return HttpResponseGone(
                "This short URL has expired."
            )

        # 4. Store the mapping in Redis. Never keep it longer than the
        #    URL's own expiry time.
        ttl = settings.CACHE_TTL_SECONDS

        if url.expires_at:
            seconds_left = int(
                (url.expires_at - timezone.now()).total_seconds()
            )

            ttl = max(1, min(ttl, seconds_left))

        cached_data = {
            "url_id": url.id,
            "original_url": url.original_url,
            "expires_at": url.expires_at,
        }

        cache.set(
            cache_key,
            cached_data,
            timeout=ttl
        )

    logger.info("CACHE %s: %s", cache_status, code)

    # 5. Extract cached values
    original_url = cached_data["original_url"]
    expires_at = cached_data["expires_at"]
    url_id = cached_data["url_id"]

    # 6. Check expiration even on a cache HIT
    if (
        expires_at
        and expires_at <= timezone.now()
    ):
        cache.delete(cache_key)

        return HttpResponseGone(
            "This short URL has expired."
        )

    # 7. Count the click (Redis Stream, or database if Redis is down).
    #    HEAD requests (link previews, curl -I) are not counted.
    if request.method == "GET":
        record_click(url_id)

    # 8. Redirect immediately
    response = redirect(original_url)

    response["X-Cache"] = cache_status

    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def url_stats(request, code):
    # Only allow the owner to see statistics
    url = get_object_or_404(
        URL,
        code=code,
        owner=request.user
    )

    return Response({
        "code": url.code,
        "original_url": url.original_url,
        "click_count": url.click_count,
        "created_at": url.created_at,
        "expires_at": url.expires_at,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_urls(request):
    urls = URL.objects.filter(
        owner=request.user
    ).order_by("-created_at")

    data = []

    for url in urls:
        data.append({
            "code": url.code,
            "original_url": url.original_url,
            "click_count": url.click_count,
            "created_at": url.created_at,
            "expires_at": url.expires_at,
        })

    return Response(data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_url(request, code):
    # Only the owner can delete the URL
    url = get_object_or_404(
        URL,
        code=code,
        owner=request.user
    )

    # Remove cached version first
    cache.delete(f"url:{code}")

    # Delete database record
    url.delete()

    return Response(
        status=status.HTTP_204_NO_CONTENT
    )