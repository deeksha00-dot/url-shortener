import re

from rest_framework import serializers


class URLCreateSerializer(serializers.Serializer):
    url = serializers.URLField()

    expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True
    )

    custom_alias = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50
    )

    def validate_custom_alias(self, value):
        if value == "":
            return value

        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise serializers.ValidationError(
                "Alias can contain only letters, numbers, '-' and '_'."
            )

        return value