from django.contrib.auth import authenticate
from django.core.cache import cache
from django.http import HttpResponseGone
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import URL
from .queue import enqueue_click
from .rate_limit import (
    get_client_ip,
    is_rate_limited,
)
from .serializers import URLCreateSerializer
from .services import create_short_url


@api_view(["POST"])
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

    short_url = request.build_absolute_uri(
        f"/{url.code}/"
    )

    return Response(
        {
            "short_url": short_url
        },
        status=status.HTTP_201_CREATED
    )


def redirect_url(request, code):
    cache_key = f"url:{code}"

    # 1. Check Redis first
    cached_data = cache.get(cache_key)

    if cached_data is None:
        print(f"CACHE MISS: {code}")

        # 2. Cache miss -> query SQLite
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

        # 4. Data stored in Redis
        cached_data = {
            "url_id": url.id,
            "original_url": url.original_url,
            "expires_at": url.expires_at,
        }

        cache.set(
            cache_key,
            cached_data,
            timeout=300
        )

    else:
        print(f"CACHE HIT: {code}")

    # 5. Extract cached values
    original_url = cached_data["original_url"]
    expires_at = cached_data["expires_at"]
    url_id = cached_data["url_id"]

    # 6. Check expiration even on Redis HIT
    if (
        expires_at
        and expires_at <= timezone.now()
    ):
        cache.delete(cache_key)

        return HttpResponseGone(
            "This short URL has expired."
        )

    # 7. Send analytics event to Redis Stream
    enqueue_click(url_id)

    # 8. Redirect immediately
    return redirect(original_url)


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