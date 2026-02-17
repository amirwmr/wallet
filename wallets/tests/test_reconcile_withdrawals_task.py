from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from wallets.domain.services import WithdrawalService
from wallets.integrations.bank_client import TransferOutcome, TransferResult
from wallets.models import Transaction, Wallet, WithdrawalReconciliationTask
from wallets.tasks.reconcile_withdrawals import reconcile_withdrawals


class ReconcileWithdrawalsTests(TestCase):
    def _schedule_due_withdrawal(self, wallet, amount):
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=amount,
            execute_at=timezone.now() + timedelta(minutes=10),
        )
        Transaction.objects.filter(pk=tx.pk).update(
            execute_at=timezone.now() - timedelta(minutes=1)
        )
        tx.refresh_from_db()
        return tx

    @override_settings(WITHDRAWAL_PROCESSING_TIMEOUT_SECONDS=1)
    def test_stale_processing_is_marked_unknown_and_queued(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = self._schedule_due_withdrawal(wallet, 200)

        Transaction.objects.filter(pk=tx.pk).update(
            status=Transaction.Status.PROCESSING,
            updated_at=timezone.now() - timedelta(seconds=120),
        )
        Wallet.objects.filter(pk=wallet.pk).update(balance=800)

        gateway = Mock()
        gateway.can_query_status.return_value = False

        summary = reconcile_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()
        task = WithdrawalReconciliationTask.objects.get(transaction=tx)

        self.assertEqual(summary["stale_marked_unknown"], 1)
        self.assertEqual(tx.status, Transaction.Status.UNKNOWN)
        self.assertEqual(wallet.balance, 800)
        self.assertEqual(task.status, WithdrawalReconciliationTask.Status.PENDING)

    def test_unknown_stays_pending_when_status_endpoint_is_missing(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = self._schedule_due_withdrawal(wallet, 200)
        Transaction.objects.filter(pk=tx.pk).update(
            status=Transaction.Status.UNKNOWN,
            failure_reason="RECONCILIATION_REQUIRED",
        )
        WithdrawalReconciliationTask.objects.create(
            transaction=tx,
            reason="UNKNOWN_TRANSFER_OUTCOME",
        )

        gateway = Mock()
        gateway.can_query_status.return_value = False

        summary = reconcile_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        task = WithdrawalReconciliationTask.objects.get(transaction=tx)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(task.status, WithdrawalReconciliationTask.Status.PENDING)

    def test_unknown_resolves_success(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = self._schedule_due_withdrawal(wallet, 200)
        Transaction.objects.filter(pk=tx.pk).update(
            status=Transaction.Status.UNKNOWN,
            failure_reason="RECONCILIATION_REQUIRED",
            bank_reference=None,
            external_reference=None,
        )
        WithdrawalReconciliationTask.objects.create(
            transaction=tx,
            reason="UNKNOWN_TRANSFER_OUTCOME",
        )

        gateway = Mock()
        gateway.can_query_status.return_value = True
        gateway.query_transfer_status.return_value = TransferResult(
            outcome=TransferOutcome.SUCCESS,
            reference="bank-ref-reconciled",
        )

        summary = reconcile_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        task = WithdrawalReconciliationTask.objects.get(transaction=tx)

        self.assertEqual(summary["resolved_success"], 1)
        self.assertEqual(tx.status, Transaction.Status.SUCCEEDED)
        self.assertEqual(tx.bank_reference, "bank-ref-reconciled")
        self.assertEqual(task.status, WithdrawalReconciliationTask.Status.RESOLVED)

    def test_unknown_resolves_final_failure_and_refunds(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = self._schedule_due_withdrawal(wallet, 200)
        Transaction.objects.filter(pk=tx.pk).update(
            status=Transaction.Status.UNKNOWN,
            failure_reason="RECONCILIATION_REQUIRED",
        )
        Wallet.objects.filter(pk=wallet.pk).update(balance=800)
        WithdrawalReconciliationTask.objects.create(
            transaction=tx,
            reason="UNKNOWN_TRANSFER_OUTCOME",
        )

        gateway = Mock()
        gateway.can_query_status.return_value = True
        gateway.query_transfer_status.return_value = TransferResult(
            outcome=TransferOutcome.FINAL_FAILURE,
            error_reason="bank_rejected",
        )

        summary = reconcile_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()
        task = WithdrawalReconciliationTask.objects.get(transaction=tx)

        self.assertEqual(summary["resolved_failure"], 1)
        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "bank_rejected")
        self.assertEqual(wallet.balance, 1_000)
        self.assertEqual(task.status, WithdrawalReconciliationTask.Status.RESOLVED)
