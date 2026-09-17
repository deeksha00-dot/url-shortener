from django.db import IntegrityError

from .models import URL
from .utils import encode_base62


def create_short_url(
    original_url,
    expires_at=None,
    custom_alias=None
):
    if custom_alias:
        try:
            return URL.objects.create(
                original_url=original_url,
                code=custom_alias,
                expires_at=expires_at
            )
        except IntegrityError:
            raise ValueError(
                "Custom alias already exists."
            )

    url = URL.objects.create(
        original_url=original_url,
        code="temporary",
        expires_at=expires_at
    )

    code = encode_base62(url.id)

    url.code = code
    url.save(update_fields=["code"])

    return url