from django.db import models
from django.db.models import Q


class Transaction(models.Model):
    class Type(models.TextChoices):
        DEPOSIT = "DEPOSIT", "Deposit"
        WITHDRAWAL = "WITHDRAWAL", "Withdrawal"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        PROCESSING = "PROCESSING", "Processing"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    wallet = models.ForeignKey(
        "wallets.Wallet",
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    type = models.CharField(max_length=16, choices=Type.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    amount = models.BigIntegerField()
    execute_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(
        max_length=128, unique=True, null=True, blank=True
    )
    external_reference = models.CharField(max_length=128, null=True, blank=True)
    bank_reference = models.CharField(max_length=128, null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["type", "status", "execute_at"],
                name="txn_type_status_execute_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="transaction_amount_gt_zero",
            ),
            models.CheckConstraint(
                condition=(
                    Q(type="DEPOSIT", execute_at__isnull=True)
                    | Q(type="WITHDRAWAL", execute_at__isnull=False)
                ),
                name="transaction_execute_at_by_type",
            ),
            models.CheckConstraint(
                condition=(
                    Q(type="DEPOSIT", idempotency_key__isnull=True)
                    | Q(type="WITHDRAWAL", idempotency_key__isnull=False)
                ),
                name="transaction_idempotency_by_type",
            ),
        ]

    def __str__(self):
        return f"Transaction<{self.pk}:{self.type}:{self.status}>"
