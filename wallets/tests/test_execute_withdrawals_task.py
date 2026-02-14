from datetime import timedelta
from io import StringIO
from threading import Thread
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.utils import timezone

from wallets.domain.services import WithdrawalService
from wallets.integrations.bank_client import TransferResult
from wallets.models import Transaction, Wallet
from wallets.tasks import execute_withdrawals as execute_withdrawals_module
from wallets.tasks.execute_withdrawals import execute_due_withdrawals


class ExecuteDueWithdrawalsTests(TestCase):
    def _schedule_due_withdrawal(self, wallet, amount):
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=amount,
            execute_at=timezone.now() + timedelta(minutes=30),
        )
        due_at = timezone.now() - timedelta(minutes=1)
        Transaction.objects.filter(pk=tx.pk).update(execute_at=due_at)
        tx.refresh_from_db()
        return tx

    def test_executes_scheduled_withdrawal_successfully(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = self._schedule_due_withdrawal(wallet, amount=300)

        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=True, reference="bank-ref-300"
        )

        summary = execute_due_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["insufficient_funds"], 0)
        self.assertEqual(tx.status, Transaction.Status.SUCCEEDED)
        self.assertEqual(tx.bank_reference, "bank-ref-300")
        self.assertEqual(tx.external_reference, "bank-ref-300")
        self.assertEqual(wallet.balance, 700)
        gateway.transfer.assert_called_once_with(
            idempotency_key=tx.idempotency_key,
            wallet_owner_ref=str(wallet.uuid),
            amount=300,
        )

    def test_marks_failed_with_insufficient_funds_at_execution_time(self):
        wallet = Wallet.objects.create(balance=100)
        tx = self._schedule_due_withdrawal(wallet, amount=150)

        gateway = Mock()

        summary = execute_due_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 0)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["insufficient_funds"], 1)
        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "INSUFFICIENT_FUNDS")
        self.assertEqual(wallet.balance, 100)
        gateway.transfer.assert_not_called()

    def test_bank_failure_refunds_wallet_and_marks_failed(self):
        wallet = Wallet.objects.create(balance=900)
        tx = self._schedule_due_withdrawal(wallet, amount=400)

        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=False, error_reason="bank_failed"
        )

        summary = execute_due_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 0)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "bank_failed")
        self.assertEqual(wallet.balance, 900)

    def test_gateway_exception_marks_failed_and_refunds_wallet(self):
        wallet = Wallet.objects.create(balance=700)
        tx = self._schedule_due_withdrawal(wallet, amount=250)

        gateway = Mock()
        gateway.transfer.side_effect = RuntimeError("unexpected upstream crash")

        summary = execute_due_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 0)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "gateway_exception:RuntimeError")
        self.assertEqual(wallet.balance, 700)

    @override_settings(WITHDRAWAL_PROCESSING_STALE_SECONDS=1)
    def test_reclaims_stale_processing_and_finishes_with_single_debit(self):
        wallet = Wallet.objects.create(balance=1_000)
        tx = self._schedule_due_withdrawal(wallet, amount=250)

        Transaction.objects.filter(pk=tx.pk).update(
            status=Transaction.Status.PROCESSING,
            updated_at=timezone.now() - timedelta(seconds=120),
        )
        Wallet.objects.filter(pk=wallet.pk).update(balance=750)

        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=True,
            reference="bank-ref-stale",
        )

        summary = execute_due_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(tx.status, Transaction.Status.SUCCEEDED)
        self.assertEqual(tx.bank_reference, "bank-ref-stale")
        self.assertEqual(wallet.balance, 750)
        gateway.transfer.assert_called_once_with(
            idempotency_key=tx.idempotency_key,
            wallet_owner_ref=str(wallet.uuid),
            amount=250,
        )

    @override_settings(WITHDRAWAL_PROCESSING_STALE_SECONDS=1)
    def test_reclaims_stale_processing_and_refunds_on_failure(self):
        wallet = Wallet.objects.create(balance=1_200)
        tx = self._schedule_due_withdrawal(wallet, amount=200)

        Transaction.objects.filter(pk=tx.pk).update(
            status=Transaction.Status.PROCESSING,
            updated_at=timezone.now() - timedelta(seconds=120),
        )
        Wallet.objects.filter(pk=wallet.pk).update(balance=1_000)

        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=False,
            error_reason="network_error",
        )

        summary = execute_due_withdrawals(limit=10, now=timezone.now(), gateway=gateway)

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 0)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(tx.status, Transaction.Status.FAILED)
        self.assertEqual(tx.failure_reason, "network_error")
        self.assertEqual(wallet.balance, 1_200)

    @override_settings(
        EXECUTOR_LOCK_CONTENTION_MAX_RETRIES=3,
        EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS=0,
    )
    def test_retries_after_lock_contention_and_completes_work(self):
        wallet = Wallet.objects.create(balance=500)
        tx = self._schedule_due_withdrawal(wallet, amount=200)
        gateway = Mock()
        gateway.transfer.return_value = TransferResult(
            success=True, reference="bank-ok"
        )

        original_claim = execute_withdrawals_module._claim_next_due_withdrawal
        calls = {"count": 0}

        def flaky_claim(now):
            if calls["count"] == 0:
                calls["count"] += 1
                raise OperationalError("database is locked")
            return original_claim(now)

        with patch(
            "wallets.tasks.execute_withdrawals._claim_next_due_withdrawal",
            side_effect=flaky_claim,
        ):
            summary = execute_due_withdrawals(
                limit=10, now=timezone.now(), gateway=gateway
            )

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(tx.status, Transaction.Status.SUCCEEDED)
        self.assertEqual(wallet.balance, 300)
        gateway.transfer.assert_called_once()

    @override_settings(
        EXECUTOR_LOCK_CONTENTION_MAX_RETRIES=1,
        EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS=0,
    )
    def test_stops_when_lock_contention_retries_are_exhausted(self):
        wallet = Wallet.objects.create(balance=400)
        tx = self._schedule_due_withdrawal(wallet, amount=100)
        gateway = Mock()

        with patch(
            "wallets.tasks.execute_withdrawals._claim_next_due_withdrawal",
            side_effect=OperationalError("database is locked"),
        ):
            summary = execute_due_withdrawals(
                limit=10, now=timezone.now(), gateway=gateway
            )

        tx.refresh_from_db()
        wallet.refresh_from_db()

        self.assertEqual(summary["processed"], 0)
        self.assertEqual(summary["succeeded"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["insufficient_funds"], 0)
        self.assertEqual(tx.status, Transaction.Status.SCHEDULED)
        self.assertEqual(wallet.balance, 400)
        gateway.transfer.assert_not_called()


class ExecuteDueWithdrawalsConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def _schedule_due_withdrawal(self, wallet, amount):
        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=amount,
            execute_at=timezone.now() + timedelta(minutes=20),
        )
        due_at = timezone.now() - timedelta(minutes=1)
        Transaction.objects.filter(pk=tx.pk).update(execute_at=due_at)
        tx.refresh_from_db()
        return tx

    def test_concurrent_runs_do_not_make_balance_negative(self):
        wallet = Wallet.objects.create(balance=100)
        tx1 = self._schedule_due_withdrawal(wallet, amount=80)
        tx2 = self._schedule_due_withdrawal(wallet, amount=80)

        fixed_now = timezone.now()
        errors = []

        class AlwaysSuccessGateway:
            @staticmethod
            def transfer(idempotency_key, wallet_owner_ref=None, amount=None):
                return TransferResult(success=True, reference=f"ref-{idempotency_key}")

        def worker():
            close_old_connections()
            try:
                execute_due_withdrawals(
                    limit=1, now=fixed_now, gateway=AlwaysSuccessGateway()
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        thread_1 = Thread(target=worker)
        thread_2 = Thread(target=worker)
        thread_1.start()
        thread_2.start()
        thread_1.join()
        thread_2.join()

        # Drain remaining due items after concurrent contenders finish.
        execute_due_withdrawals(limit=10, now=fixed_now, gateway=AlwaysSuccessGateway())

        tx1.refresh_from_db()
        tx2.refresh_from_db()
        wallet.refresh_from_db()

        if errors:
            self.assertTrue(all(isinstance(err, OperationalError) for err in errors))
        self.assertGreaterEqual(wallet.balance, 0)

        statuses = [tx1.status, tx2.status]
        self.assertLessEqual(statuses.count(Transaction.Status.SUCCEEDED), 1)
        self.assertGreaterEqual(statuses.count(Transaction.Status.FAILED), 1)


class WithdrawalExecutorCommandTests(TestCase):
    @patch(
        "wallets.management.commands.run_withdrawal_executor.execute_due_withdrawals"
    )
    def test_command_runs_once(self, execute_mock):
        execute_mock.return_value = {
            "processed": 1,
            "succeeded": 1,
            "failed": 0,
            "insufficient_funds": 0,
        }
        stdout = StringIO()

        call_command("run_withdrawal_executor", limit=2, stdout=stdout)

        execute_mock.assert_called_once()
        self.assertIn("processed=1", stdout.getvalue())

    def test_command_rejects_non_positive_limit(self):
        with self.assertRaises(CommandError):
            call_command("run_withdrawal_executor", limit=0)
