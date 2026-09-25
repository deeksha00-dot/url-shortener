from django.db import IntegrityError

from .models import URL
from .utils import encode_base62


def create_short_url(
    original_url,
    expires_at=None,
    custom_alias=None,
    owner=None
):
    # Custom alias provided by the user
    if custom_alias:
        try:
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

    # Create a temporary record first so that
    # the database generates the ID.
    url = URL.objects.create(
        original_url=original_url,
        code="temporary",
        expires_at=expires_at,
        owner=owner
    )

    # Convert database ID to Base62
    code = encode_base62(url.id)

    # Update the temporary code
    url.code = code
    url.save(update_fields=["code"])

    return url