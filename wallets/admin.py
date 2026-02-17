from django.contrib import admin

from wallets.models import Transaction, Wallet, WithdrawalReconciliationTask


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "uuid", "balance", "created_at", "updated_at")
    search_fields = ("id", "uuid")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "type",
        "status",
        "amount",
        "execute_at",
        "idempotency_key",
        "created_at",
    )
    list_filter = ("type", "status")
    search_fields = ("id", "idempotency_key", "external_reference", "bank_reference")


@admin.register(WithdrawalReconciliationTask)
class WithdrawalReconciliationTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "transaction", "status", "reason", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("id", "transaction__id", "transaction__idempotency_key", "reason")
