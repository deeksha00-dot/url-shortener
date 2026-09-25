from django.contrib.auth.models import User
from django.db import models


class URL(models.Model):
    code = models.CharField(
        max_length=50,
        unique=True
    )

    original_url = models.URLField()

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="urls",
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True
    )

    click_count = models.PositiveBigIntegerField(
        default=0
    )

    def __str__(self):
        return self.code


class ClickEvent(models.Model):
    event_id = models.CharField(
        max_length=100,
        unique=True
    )

    url = models.ForeignKey(
        URL,
        on_delete=models.CASCADE,
        related_name="click_events"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.event_id