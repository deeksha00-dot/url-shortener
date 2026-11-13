import re
from urllib.parse import urlparse

from django.utils import timezone
from rest_framework import serializers

from .services import RESERVED_CODES


ALLOWED_SCHEMES = ("http", "https")


class URLCreateSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=2048)

    expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True
    )

    custom_alias = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50
    )

    def validate_url(self, value):
        # Django's URLField also accepts ftp:// and ftps://.
        # Only allow web links so a short link can never point at
        # javascript:, file:, data:, ftp: and similar schemes.
        if urlparse(value).scheme.lower() not in ALLOWED_SCHEMES:
            raise serializers.ValidationError(
                "Only http:// and https:// URLs are allowed."
            )

        return value

    def validate_expires_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError(
                "Expiration must be in the future."
            )

        return value

    def validate_custom_alias(self, value):
        if value == "":
            return value

        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise serializers.ValidationError(
                "Alias can contain only letters, numbers, '-' and '_'."
            )

        if value.lower() in RESERVED_CODES:
            raise serializers.ValidationError(
                "This alias is reserved. Please choose another one."
            )

        return value


class RegisterSerializer(serializers.Serializer):
    username = serializers.RegexField(
        r"^[\w.@+-]+$",
        max_length=150
    )

    password = serializers.CharField(
        write_only=True,
        max_length=128
    )

    def validate_username(self, value):
        from django.contrib.auth.models import User

        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError(
                "This username is already taken."
            )

        return value

    def validate_password(self, value):
        from django.contrib.auth.password_validation import (
            validate_password
        )
        from django.core.exceptions import ValidationError

        try:
            validate_password(value)
        except ValidationError as error:
            raise serializers.ValidationError(list(error.messages))

        return value
