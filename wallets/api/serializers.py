from rest_framework import serializers

from wallets.models import Transaction, Wallet


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ("id", "uuid", "balance", "created_at", "updated_at")
        read_only_fields = ("id", "uuid", "balance", "created_at", "updated_at")


class DepositRequestSerializer(serializers.Serializer):
    amount = serializers.IntegerField()


class ScheduleWithdrawalRequestSerializer(serializers.Serializer):
    amount = serializers.IntegerField()
    execute_at = serializers.DateTimeField()
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=128,
    )


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "id",
            "wallet_id",
            "type",
            "status",
            "amount",
            "execute_at",
            "idempotency_key",
            "external_reference",
            "bank_reference",
            "failure_reason",
            "created_at",
            "updated_at",
        )


class TransactionFilterSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=Transaction.Type.values,
        required=False,
    )
    status = serializers.ChoiceField(
        choices=Transaction.Status.values,
        required=False,
    )
