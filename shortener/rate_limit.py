import time

from django.core.cache import cache


def get_client_ip(request):
    return request.META.get(
        "REMOTE_ADDR",
        "unknown"
    )


def is_rate_limited(
    key_prefix,
    identifier,
    limit,
    window_seconds=60
):
    window = int(time.time() // window_seconds)

    key = (
        f"rate:{key_prefix}:"
        f"{identifier}:{window}"
    )

    created = cache.add(
        key,
        1,
        timeout=window_seconds
    )

    # cache.add() returns None (not True/False) when Redis is unreachable.
    # Without Redis we cannot count requests, so allow them (fail open)
    # instead of blocking every user.
    if created is None:
        return False

    if created:
        return False

    try:
        count = cache.incr(key)
    except ValueError:
        count = 1
        cache.set(
            key,
            count,
            timeout=window_seconds
        )

    if count is None:
        return False

    return count > limit
