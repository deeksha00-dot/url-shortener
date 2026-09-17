from django.core.cache import cache
from django.db.models import F
from django.http import HttpResponseGone
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import URL
from .serializers import URLCreateSerializer
from .services import create_short_url


@api_view(["POST"])
def shorten_url(request):
    serializer = URLCreateSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        url = create_short_url(
            serializer.validated_data["url"],
            serializer.validated_data.get("expires_at"),
            serializer.validated_data.get("custom_alias")
        )
    except ValueError as e:
        return Response(
            {"error": str(e)},
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

    cached_data = cache.get(cache_key)

    if cached_data is None:
        print(f"CACHE MISS: {code}")

        url = get_object_or_404(
            URL,
            code=code
        )

        if url.expires_at and url.expires_at <= timezone.now():
            return HttpResponseGone(
                "This short URL has expired."
            )

        cached_data = {
            "original_url": url.original_url,
            "expires_at": url.expires_at,
        }

        cache.set(
            cache_key,
            cached_data,
            timeout=300
        )

    original_url = cached_data["original_url"]
    expires_at = cached_data["expires_at"]

    if expires_at and expires_at <= timezone.now():
        cache.delete(cache_key)

        return HttpResponseGone(
            "This short URL has expired."
        )

    URL.objects.filter(
        code=code
    ).update(
        click_count=F("click_count") + 1
    )

    return redirect(original_url)


@api_view(["GET"])
def url_stats(request, code):
    url = get_object_or_404(
        URL,
        code=code
    )

    return Response({
        "code": url.code,
        "original_url": url.original_url,
        "click_count": url.click_count,
        "created_at": url.created_at,
        "expires_at": url.expires_at,
    })