from rest_framework import serializers

from wallets.domain.constants import TransactionStatus, TransactionType
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
        choices=[item.value for item in TransactionType],
        required=False,
    )
    status = serializers.ChoiceField(
        choices=[item.value for item in TransactionStatus],
        required=False,
    )
