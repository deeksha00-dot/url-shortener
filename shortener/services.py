import logging

import redis
from django.db import IntegrityError, transaction
from django.db.models import F

from .models import URL
from .queue import enqueue_click
from .utils import generate_short_code


logger = logging.getLogger(__name__)

# Paths that already belong to the application. A short code with one of
# these names could never be reached, so they cannot be used as aliases.
RESERVED_CODES = {"api", "admin", "app", "static"}

# How many random codes to try before giving up.
MAX_CODE_ATTEMPTS = 5


def create_short_url(
    original_url,
    expires_at=None,
    custom_alias=None,
    owner=None
):
    # Custom alias provided by the user
    if custom_alias:
        try:
            with transaction.atomic():
                return URL.objects.create(
                    original_url=original_url,
                    code=custom_alias,
                    expires_at=expires_at,
                    owner=owner
                )
        except IntegrityError:
            raise ValueError(
                "Custom alias already exists."
            )

    # Generated code: try a random code and rely on the database's UNIQUE
    # constraint to detect a collision. On collision, try another code.
    # (Checking "does it exist?" first would be a race condition.)
    for _ in range(MAX_CODE_ATTEMPTS):
        try:
            with transaction.atomic():
                return URL.objects.create(
                    original_url=original_url,
                    code=generate_short_code(),
                    expires_at=expires_at,
                    owner=owner
                )
        except IntegrityError:
            continue

    raise RuntimeError(
        "Could not generate a unique short code. Please try again."
    )


def record_click(url_id):
    """Count one click for a URL.

    Normal path: push an event to the Redis Stream and let the worker
    update the database later (the redirect stays fast).

    Fallback: if Redis is unreachable, update the database directly so the
    click is not lost.
    """
    try:
        enqueue_click(url_id)

    except redis.exceptions.RedisError as error:
        logger.warning(
            "Redis unavailable (%s); counting click directly in the database.",
            error
        )

        URL.objects.filter(
            id=url_id
        ).update(
            click_count=F("click_count") + 1
        )
