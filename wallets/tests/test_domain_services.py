from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from wallets.domain.exceptions import (
    IdempotencyConflict,
    InvalidAmount,
    InvalidExecuteAt,
    InvalidIdempotencyKey,
    WalletNotFound,
)
from wallets.domain.services import WalletService, WithdrawalService
from wallets.models import Transaction, Wallet


class WalletServiceDepositTests(TestCase):
    def test_deposit_updates_balance_and_creates_succeeded_transaction(self):
        wallet = Wallet.objects.create(balance=1_000)

        tx = WalletService.deposit(wallet_id=wallet.id, amount=250)

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 1_250)
        self.assertEqual(tx.wallet_id, wallet.id)
        self.assertEqual(tx.type, Transaction.Type.DEPOSIT)
        self.assertEqual(tx.status, Transaction.Status.SUCCEEDED)
        self.assertEqual(tx.amount, 250)
        self.assertIsNone(tx.execute_at)
        self.assertIsNone(tx.idempotency_key)

    def test_deposit_rejects_non_positive_amount(self):
        wallet = Wallet.objects.create(balance=1_000)

        for invalid in (0, -10):
            with self.subTest(invalid=invalid):
                with self.assertRaises(InvalidAmount):
                    WalletService.deposit(wallet_id=wallet.id, amount=invalid)

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 1_000)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_deposit_raises_when_wallet_does_not_exist(self):
        with self.assertRaises(WalletNotFound):
            WalletService.deposit(wallet_id=999_999, amount=100)

    def test_deposit_reuses_existing_transaction_for_same_idempotency_key(self):
        wallet = Wallet.objects.create(balance=1_000)

        first = WalletService.deposit(
            wallet_id=wallet.id,
            amount=250,
            idempotency_key="deposit-001",
        )
        second = WalletService.deposit(
            wallet_id=wallet.id,
            amount=250,
            idempotency_key="deposit-001",
        )

        wallet.refresh_from_db()
        self.assertEqual(first.id, second.id)
        self.assertEqual(wallet.balance, 1_250)
        self.assertEqual(
            Transaction.objects.filter(idempotency_key="deposit-001").count(),
            1,
        )

    def test_deposit_rejects_idempotency_key_conflict(self):
        wallet = Wallet.objects.create(balance=1_000)

        WalletService.deposit(
            wallet_id=wallet.id,
            amount=250,
            idempotency_key="deposit-002",
        )

        with self.assertRaises(IdempotencyConflict):
            WalletService.deposit(
                wallet_id=wallet.id,
                amount=350,
                idempotency_key="deposit-002",
            )

    def test_deposit_rejects_empty_idempotency_key(self):
        wallet = Wallet.objects.create(balance=1_000)

        with self.assertRaises(InvalidIdempotencyKey):
            WalletService.deposit(
                wallet_id=wallet.id,
                amount=100,
                idempotency_key="  ",
            )


class WithdrawalServiceScheduleTests(TestCase):
    def test_schedule_withdrawal_creates_scheduled_transaction(self):
        wallet = Wallet.objects.create(balance=100)
        execute_at = timezone.now() + timedelta(hours=1)

        tx = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=500,
            execute_at=execute_at,
        )

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 100)
        self.assertEqual(tx.wallet_id, wallet.id)
        self.assertEqual(tx.type, Transaction.Type.WITHDRAWAL)
        self.assertEqual(tx.status, Transaction.Status.SCHEDULED)
        self.assertEqual(tx.amount, 500)
        self.assertEqual(tx.execute_at, execute_at)
        self.assertTrue(tx.idempotency_key)

    def test_schedule_withdrawal_rejects_non_positive_amount(self):
        wallet = Wallet.objects.create(balance=100)
        execute_at = timezone.now() + timedelta(hours=1)

        for invalid in (0, -1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(InvalidAmount):
                    WithdrawalService.schedule_withdrawal(
                        wallet_id=wallet.id,
                        amount=invalid,
                        execute_at=execute_at,
                    )

        self.assertEqual(Transaction.objects.count(), 0)

    def test_schedule_withdrawal_rejects_non_future_execute_at(self):
        wallet = Wallet.objects.create(balance=100)

        for invalid_execute_at in (
            timezone.now(),
            timezone.now() - timedelta(seconds=1),
        ):
            with self.subTest(invalid_execute_at=invalid_execute_at):
                with self.assertRaises(InvalidExecuteAt):
                    WithdrawalService.schedule_withdrawal(
                        wallet_id=wallet.id,
                        amount=10,
                        execute_at=invalid_execute_at,
                    )

        self.assertEqual(Transaction.objects.count(), 0)

    def test_schedule_withdrawal_raises_when_wallet_does_not_exist(self):
        execute_at = timezone.now() + timedelta(hours=1)

        with self.assertRaises(WalletNotFound):
            WithdrawalService.schedule_withdrawal(
                wallet_id=999_999,
                amount=10,
                execute_at=execute_at,
            )

    def test_schedule_withdrawal_reuses_existing_transaction_for_same_idempotency_key(
        self,
    ):
        wallet = Wallet.objects.create(balance=100)
        execute_at = timezone.now() + timedelta(hours=1)

        first = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=50,
            execute_at=execute_at,
            idempotency_key="withdraw-001",
        )
        second = WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=50,
            execute_at=execute_at,
            idempotency_key="withdraw-001",
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(
            Transaction.objects.filter(idempotency_key="withdraw-001").count(),
            1,
        )

    def test_schedule_withdrawal_rejects_idempotency_key_conflict(self):
        wallet = Wallet.objects.create(balance=100)
        execute_at = timezone.now() + timedelta(hours=1)

        WithdrawalService.schedule_withdrawal(
            wallet_id=wallet.id,
            amount=50,
            execute_at=execute_at,
            idempotency_key="withdraw-002",
        )

        with self.assertRaises(IdempotencyConflict):
            WithdrawalService.schedule_withdrawal(
                wallet_id=wallet.id,
                amount=70,
                execute_at=execute_at,
                idempotency_key="withdraw-002",
            )

    def test_schedule_withdrawal_rejects_empty_idempotency_key(self):
        wallet = Wallet.objects.create(balance=100)
        execute_at = timezone.now() + timedelta(hours=1)

        with self.assertRaises(InvalidIdempotencyKey):
            WithdrawalService.schedule_withdrawal(
                wallet_id=wallet.id,
                amount=50,
                execute_at=execute_at,
                idempotency_key="  ",
            )
