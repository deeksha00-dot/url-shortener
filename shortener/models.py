from django.db import models


class URL(models.Model):
    code = models.CharField(
        max_length=50,
        unique=True
    )

    original_url = models.URLField()

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