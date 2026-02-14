from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from wallets.domain.exceptions import InvalidTransactionState
from wallets.domain.services import WithdrawalService
from wallets.integrations.bank_client import TransferResult
from wallets.integrations.idempotency import (
    ensure_transaction_idempotency_key,
    generate_idempotency_key,
)
from wallets.models import Transaction, Wallet


class IdempotencyHelpersTests(TestCase):
    def test_generate_idempotency_key_returns_unique_values(self):
        first = generate_idempotency_key()
        second = generate_idempotency_key()

        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertEqual(len(second), 32)

    def test_ensure_returns_existing_withdrawal_key(self):
        wallet = Wallet.objects.create(balance=500)
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=100,
            execute_at=timezone.now() + timedelta(minutes=30),
        )

        original = tx.idempotency_key
        ensured = ensure_transaction_idempotency_key(tx)

        self.assertEqual(ensured, original)

    def test_ensure_raises_for_deposit_transaction(self):
        wallet = Wallet.objects.create(balance=500)
        tx = Transaction.objects.create(
            wallet=wallet,
            type="DEPOSIT",
            status="SUCCEEDED",
            amount=100,
        )

        with self.assertRaises(ValueError):
            ensure_transaction_idempotency_key(tx)


class WithdrawalExecuteTests(TestCase):
    @staticmethod
    def _force_due(tx):
        Transaction.objects.filter(pk=tx.pk).update(
            execute_at=timezone.now() - timedelta(seconds=1)
        )
        tx.refresh_from_db()
        return tx

    def test_execute_withdrawal_success_marks_succeeded_and_keeps_debit(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=300,
            execute_at=timezone.now() + timedelta(minutes=10),
        )
        tx = self._force_due(tx)

        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=True,
            reference="bank-ref-1",
            error_reason=None,
        )

        WithdrawalService.execute_withdrawal(tx.id, gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(tx.status, Transaction.Status.SUCCEEDED)
        self.assertEqual(tx.bank_reference, "bank-ref-1")
        self.assertEqual(tx.external_reference, "bank-ref-1")
        self.assertEqual(wallet.balance, 700)
        gateway.transfer.assert_called_once_with(
            idempotency_key=tx.idempotency_key,
            wallet_owner_ref=str(wallet.uuid),
            amount=300,
        )

    def test_execute_withdrawal_failure_refunds_wallet_and_marks_failed(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=200,
            execute_at=timezone.now() + timedelta(minutes=10),
        )
        tx = self._force_due(tx)

        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=False,
            reference=None,
            error_reason="bank_unavailable",
        )

        WithdrawalService.execute_withdrawal(tx.id, gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "bank_unavailable")
        self.assertEqual(wallet.balance, 1_000)

    def test_execute_withdrawal_network_failure_refunds_wallet(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=150,
            execute_at=timezone.now() + timedelta(minutes=10),
        )
        tx = self._force_due(tx)

        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=False,
            reference=None,
            error_reason="network_error",
        )

        WithdrawalService.execute_withdrawal(tx.id, gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "network_error")
        self.assertEqual(wallet.balance, 1_000)

    def test_execute_withdrawal_gateway_exception_refunds_wallet(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=150,
            execute_at=timezone.now() + timedelta(minutes=10),
        )
        tx = self._force_due(tx)

        gateway = Mock()
        gateway.transfer.side_effect = RuntimeError("bank process crashed")

        WithdrawalService.execute_withdrawal(tx.id, gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "gateway_exception:RuntimeError")
        self.assertEqual(wallet.balance, 1_000)

    def test_execute_withdrawal_insufficient_balance_marks_failed_without_gateway_call(
        self,
    ):
        wallet = Wallet.objects.create(balance=100)
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=200,
            execute_at=timezone.now() + timedelta(minutes=10),
        )
        tx = self._force_due(tx)

        gateway = Mock()

        WithdrawalService.execute_withdrawal(tx.id, gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "insufficient_balance")
        self.assertEqual(wallet.balance, 100)
        gateway.transfer.assert_not_called()

    def test_execute_withdrawal_rejects_when_not_due(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=200,
            execute_at=timezone.now() + timedelta(minutes=10),
        )

        gateway = Mock()

        with self.assertRaises(InvalidTransactionState):
            WithdrawalService.execute_withdrawal(tx.id, gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()
        self.assertEqual(tx.status, Transaction.Status.SCHEDULED)
        self.assertEqual(wallet.balance, 1_000)
        gateway.transfer.assert_not_called()
