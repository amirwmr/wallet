import uuid

from django.db import models
from django.db.models import Q


class Wallet(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    balance = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(balance__gte=0),
                name="wallet_balance_non_negative",
            ),
        ]

    def __str__(self):
        return f"Wallet<{self.pk}>"
