from django.db import transaction
from django.db.models import F

from wallets.domain.exceptions import InvalidTransactionState, WalletNotFound
from wallets.domain.policies import validate_future_execute_at, validate_positive_amount
from wallets.integrations.bank_client import BankGateway
from wallets.integrations.idempotency import (
    ensure_transaction_idempotency_key,
    generate_idempotency_key,
)
from wallets.models import Transaction, Wallet


class WalletService:
    @staticmethod
    def deposit(wallet_id, amount):
        validated_amount = validate_positive_amount(amount)

        with transaction.atomic():
            try:
                wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
            except Wallet.DoesNotExist as exc:
                raise WalletNotFound(f"wallet={wallet_id} does not exist") from exc

            Wallet.objects.filter(pk=wallet.pk).update(
                balance=F("balance") + validated_amount
            )
            wallet.refresh_from_db(fields=["balance", "updated_at"])

            tx = Transaction.objects.create(
                wallet=wallet,
                type=Transaction.Type.DEPOSIT,
                status=Transaction.Status.SUCCEEDED,
                amount=validated_amount,
            )

        return tx


class WithdrawalService:
    @staticmethod
    def schedule_withdrawal(wallet_id, amount, execute_at):
        validated_amount = validate_positive_amount(amount)
        validated_execute_at = validate_future_execute_at(execute_at)

        try:
            wallet = Wallet.objects.get(pk=wallet_id)
        except Wallet.DoesNotExist as exc:
            raise WalletNotFound(f"wallet={wallet_id} does not exist") from exc

        tx = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.SCHEDULED,
            amount=validated_amount,
            execute_at=validated_execute_at,
            idempotency_key=generate_idempotency_key(),
        )
        return tx

    @staticmethod
    def execute_withdrawal(transaction_id, *, gateway=None):
        bank_gateway = gateway or BankGateway()

        with transaction.atomic():
            try:
                tx = (
                    Transaction.objects.select_for_update()
                    .select_related("wallet")
                    .get(pk=transaction_id)
                )
            except Transaction.DoesNotExist as exc:
                raise InvalidTransactionState(
                    f"transaction={transaction_id} does not exist"
                ) from exc

            if tx.type != Transaction.Type.WITHDRAWAL:
                raise InvalidTransactionState(
                    "only withdrawal transactions can be executed"
                )

            if tx.status != Transaction.Status.SCHEDULED:
                raise InvalidTransactionState(
                    f"transaction status must be {Transaction.Status.SCHEDULED}, got={tx.status}"
                )

            wallet = Wallet.objects.select_for_update().get(pk=tx.wallet_id)
            tx.status = Transaction.Status.PROCESSING
            tx.failure_reason = None
            tx.save(update_fields=["status", "failure_reason", "updated_at"])

            if wallet.balance < tx.amount:
                tx.status = Transaction.Status.FAILED
                tx.failure_reason = "insufficient_balance"
                tx.save(update_fields=["status", "failure_reason", "updated_at"])
                return tx

            Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") - tx.amount)
            tx.idempotency_key = ensure_transaction_idempotency_key(tx)
            tx.save(update_fields=["idempotency_key", "updated_at"])

        transfer_result = bank_gateway.transfer(
            idempotency_key=tx.idempotency_key,
            wallet_owner_ref=str(tx.wallet.uuid),
            amount=tx.amount,
        )

        with transaction.atomic():
            tx = (
                Transaction.objects.select_for_update()
                .select_related("wallet")
                .get(pk=transaction_id)
            )
            wallet = Wallet.objects.select_for_update().get(pk=tx.wallet_id)

            if transfer_result.success:
                tx.status = Transaction.Status.SUCCEEDED
                tx.external_reference = transfer_result.reference
                tx.bank_reference = transfer_result.reference
                tx.failure_reason = None
                tx.save(
                    update_fields=[
                        "status",
                        "external_reference",
                        "bank_reference",
                        "failure_reason",
                        "updated_at",
                    ]
                )
                return tx

            Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") + tx.amount)
            tx.status = Transaction.Status.FAILED
            tx.failure_reason = transfer_result.error_reason or "bank_transfer_failed"
            tx.save(update_fields=["status", "failure_reason", "updated_at"])
            return tx
