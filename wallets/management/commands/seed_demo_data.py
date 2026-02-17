from datetime import timedelta
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from wallets.models import Transaction, Wallet, WithdrawalReconciliationTask


class Command(BaseCommand):
    help = "Seed demo users and wallet data for local testing."

    def handle(self, *args, **options):
        now = timezone.now()

        with transaction.atomic():
            user_summary = self._seed_users()
            wallet_summary = self._seed_wallets_and_transactions(now=now)

        self.stdout.write(self.style.SUCCESS("Demo seed completed."))
        self.stdout.write(
            "Login credentials: admin / admin "
            "(for local demo only, change in production)."
        )
        self.stdout.write(
            (
                f"Users created={user_summary['created']} "
                f"updated={user_summary['updated']}"
            )
        )
        self.stdout.write(
            (
                f"Wallets created={wallet_summary['wallets_created']} "
                f"updated={wallet_summary['wallets_updated']}"
            )
        )
        self.stdout.write(
            (
                f"Transactions created={wallet_summary['transactions_created']} "
                f"updated={wallet_summary['transactions_updated']}"
            )
        )
        self.stdout.write(
            (
                "Reconciliation tasks "
                f"created={wallet_summary['recon_created']} "
                f"updated={wallet_summary['recon_updated']}"
            )
        )
        self.stdout.write(f"Wallet IDs: {', '.join(wallet_summary['wallet_ids'])}")

    def _seed_users(self):
        User = get_user_model()
        created = 0
        updated = 0

        users = [
            {
                "username": "admin",
                "password": "admin",
                "email": "admin@example.com",
                "is_staff": True,
                "is_superuser": True,
                "first_name": "Admin",
                "last_name": "User",
            },
            {
                "username": "demo_manager",
                "password": "demo123",
                "email": "manager@example.com",
                "is_staff": True,
                "is_superuser": False,
                "first_name": "Demo",
                "last_name": "Manager",
            },
            {
                "username": "demo_ops",
                "password": "demo123",
                "email": "ops@example.com",
                "is_staff": True,
                "is_superuser": False,
                "first_name": "Demo",
                "last_name": "Ops",
            },
            {
                "username": "demo_user",
                "password": "demo123",
                "email": "user@example.com",
                "is_staff": False,
                "is_superuser": False,
                "first_name": "Demo",
                "last_name": "User",
            },
        ]

        username_field = User.USERNAME_FIELD
        model_fields = {field.name for field in User._meta.fields}

        for payload in users:
            username = payload["username"]
            lookup = {username_field: username}
            defaults = {}
            if "email" in model_fields:
                defaults["email"] = payload["email"]

            user, was_created = User.objects.get_or_create(
                **lookup,
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

            user.is_active = True
            user.is_staff = payload["is_staff"]
            user.is_superuser = payload["is_superuser"]
            if "email" in model_fields:
                user.email = payload["email"]
            if "first_name" in model_fields:
                user.first_name = payload["first_name"]
            if "last_name" in model_fields:
                user.last_name = payload["last_name"]
            user.set_password(payload["password"])
            user.save()

        return {"created": created, "updated": updated}

    def _seed_wallets_and_transactions(self, *, now):
        wallets_created = 0
        wallets_updated = 0
        transactions_created = 0
        transactions_updated = 0
        recon_created = 0
        recon_updated = 0

        def upsert_wallet(wallet_uuid, balance):
            nonlocal wallets_created, wallets_updated
            wallet, created = Wallet.objects.update_or_create(
                uuid=UUID(wallet_uuid),
                defaults={"balance": balance},
            )
            if created:
                wallets_created += 1
            else:
                wallets_updated += 1
            return wallet

        def upsert_transaction(idempotency_key, **defaults):
            nonlocal transactions_created, transactions_updated
            tx, created = Transaction.objects.update_or_create(
                idempotency_key=idempotency_key,
                defaults=defaults,
            )
            if created:
                transactions_created += 1
            else:
                transactions_updated += 1
            return tx

        wallet_a = upsert_wallet("11111111-1111-1111-1111-111111111111", 120_000)
        wallet_b = upsert_wallet("22222222-2222-2222-2222-222222222222", 45_000)
        wallet_c = upsert_wallet("33333333-3333-3333-3333-333333333333", 3_000)

        upsert_transaction(
            "demo-deposit-a-001",
            wallet=wallet_a,
            type=Transaction.Type.DEPOSIT,
            status=Transaction.Status.SUCCEEDED,
            amount=150_000,
            execute_at=None,
            external_reference=None,
            bank_reference=None,
            failure_reason=None,
        )
        upsert_transaction(
            "demo-withdrawal-a-001",
            wallet=wallet_a,
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.SUCCEEDED,
            amount=30_000,
            execute_at=now - timedelta(days=2),
            external_reference="bank-demo-a-001",
            bank_reference="bank-demo-a-001",
            failure_reason=None,
        )
        upsert_transaction(
            "demo-withdrawal-a-002",
            wallet=wallet_a,
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.SCHEDULED,
            amount=20_000,
            execute_at=now + timedelta(hours=1),
            external_reference=None,
            bank_reference=None,
            failure_reason=None,
        )

        upsert_transaction(
            "demo-deposit-b-001",
            wallet=wallet_b,
            type=Transaction.Type.DEPOSIT,
            status=Transaction.Status.SUCCEEDED,
            amount=50_000,
            execute_at=None,
            external_reference=None,
            bank_reference=None,
            failure_reason=None,
        )
        upsert_transaction(
            "demo-withdrawal-b-001",
            wallet=wallet_b,
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.SUCCEEDED,
            amount=5_000,
            execute_at=now - timedelta(days=1, hours=1),
            external_reference="bank-demo-b-001",
            bank_reference="bank-demo-b-001",
            failure_reason=None,
        )
        upsert_transaction(
            "demo-withdrawal-b-002",
            wallet=wallet_b,
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.FAILED,
            amount=3_000,
            execute_at=now - timedelta(days=1),
            external_reference=None,
            bank_reference=None,
            failure_reason="bank_rejected",
        )

        upsert_transaction(
            "demo-deposit-c-001",
            wallet=wallet_c,
            type=Transaction.Type.DEPOSIT,
            status=Transaction.Status.SUCCEEDED,
            amount=10_000,
            execute_at=None,
            external_reference=None,
            bank_reference=None,
            failure_reason=None,
        )
        unknown_tx = upsert_transaction(
            "demo-withdrawal-c-001",
            wallet=wallet_c,
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.UNKNOWN,
            amount=7_000,
            execute_at=now - timedelta(hours=12),
            external_reference=None,
            bank_reference=None,
            failure_reason="network_timeout",
        )
        upsert_transaction(
            "demo-withdrawal-c-002",
            wallet=wallet_c,
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.SCHEDULED,
            amount=2_500,
            execute_at=now + timedelta(minutes=30),
            external_reference=None,
            bank_reference=None,
            failure_reason=None,
        )

        task, created = WithdrawalReconciliationTask.objects.update_or_create(
            transaction=unknown_tx,
            defaults={
                "reason": "DEMO_UNKNOWN_TRANSFER",
                "status": WithdrawalReconciliationTask.Status.PENDING,
            },
        )
        if created:
            recon_created += 1
        else:
            recon_updated += 1

        return {
            "wallets_created": wallets_created,
            "wallets_updated": wallets_updated,
            "transactions_created": transactions_created,
            "transactions_updated": transactions_updated,
            "recon_created": recon_created,
            "recon_updated": recon_updated,
            "wallet_ids": [str(wallet_a.id), str(wallet_b.id), str(wallet_c.id)],
        }
