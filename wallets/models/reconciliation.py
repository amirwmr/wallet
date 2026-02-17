from django.db import models


class WithdrawalReconciliationTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RESOLVED = "RESOLVED", "Resolved"

    transaction = models.OneToOneField(
        "wallets.Transaction",
        on_delete=models.PROTECT,
        related_name="reconciliation_task",
    )
    reason = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["status", "created_at"], name="recon_status_created_idx"
            )
        ]

    def __str__(self):
        return f"ReconciliationTask<{self.pk}:{self.transaction_id}:{self.status}>"
