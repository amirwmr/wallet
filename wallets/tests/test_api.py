from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from wallets.domain.services import WalletService, WithdrawalService
from wallets.models import Transaction, Wallet


class WalletPhase4ApiTests(APITestCase):
    def setUp(self):
        self.wallet = Wallet.objects.create(balance=1_000)

    def test_deposit_endpoint_success(self):
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            {"amount": 250},
            format="json",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], 201)
        self.assertIn("detail", response.data)
        self.assertIn("message", response.data)
        self.assertIn("data", response.data)
        self.assertEqual(self.wallet.balance, 1_250)
        self.assertEqual(response.data["data"]["transaction"]["type"], "DEPOSIT")
        self.assertEqual(response.data["data"]["transaction"]["status"], "SUCCEEDED")

    def test_deposit_endpoint_is_idempotent_with_header_key(self):
        path = f"/api/wallets/{self.wallet.id}/deposit/"

        first = self.client.post(
            path,
            {"amount": 250},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-deposit-001",
        )
        second = self.client.post(
            path,
            {"amount": 250},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-deposit-001",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["status"], 201)
        self.assertEqual(second.data["status"], 200)
        self.assertEqual(
            first.data["data"]["transaction"]["id"],
            second.data["data"]["transaction"]["id"],
        )
        self.assertEqual(self.wallet.balance, 1_250)
        self.assertEqual(
            Transaction.objects.filter(idempotency_key="api-deposit-001").count(),
            1,
        )

    def test_deposit_endpoint_rejects_idempotency_payload_conflict(self):
        path = f"/api/wallets/{self.wallet.id}/deposit/"

        first = self.client.post(
            path,
            {"amount": 120},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-deposit-002",
        )
        second = self.client.post(
            path,
            {"amount": 130},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-deposit-002",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data["status"], 409)

    def test_deposit_endpoint_rejects_idempotency_header_body_mismatch(self):
        path = f"/api/wallets/{self.wallet.id}/deposit/"

        response = self.client.post(
            path,
            {"amount": 150, "idempotency_key": "body-deposit-key"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="header-deposit-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], 400)
        self.assertIn("detail", response.data)

    def test_schedule_withdrawal_endpoint_success(self):
        execute_at = (timezone.now() + timedelta(minutes=30)).isoformat()

        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/withdrawals/",
            {"amount": 400, "execute_at": execute_at},
            format="json",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], 201)
        self.assertEqual(self.wallet.balance, 1_000)
        self.assertEqual(response.data["data"]["transaction"]["type"], "WITHDRAWAL")
        self.assertEqual(response.data["data"]["transaction"]["status"], "SCHEDULED")
        self.assertIsNotNone(response.data["data"]["transaction"]["idempotency_key"])

    def test_wallet_detail_endpoint_with_recent_transactions(self):
        WalletService.deposit(wallet_id=self.wallet.id, amount=200)
        WithdrawalService.schedule_withdrawal(
            wallet_id=self.wallet.id,
            amount=100,
            execute_at=timezone.now() + timedelta(minutes=15),
        )

        response = self.client.get(f"/api/wallets/{self.wallet.id}/?recent=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], 200)
        self.assertEqual(response.data["data"]["wallet"]["id"], self.wallet.id)
        self.assertEqual(len(response.data["data"]["recent_transactions"]), 1)

    def test_transactions_endpoint_filters_by_type_and_status(self):
        WalletService.deposit(wallet_id=self.wallet.id, amount=100)
        WithdrawalService.schedule_withdrawal(
            wallet_id=self.wallet.id,
            amount=80,
            execute_at=timezone.now() + timedelta(minutes=20),
        )

        response = self.client.get(
            f"/api/wallets/{self.wallet.id}/transactions/?type=DEPOSIT&status=SUCCEEDED"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], 200)
        self.assertEqual(response.data["data"]["count"], 1)
        self.assertEqual(response.data["data"]["results"][0]["type"], "DEPOSIT")
        self.assertEqual(response.data["data"]["results"][0]["status"], "SUCCEEDED")

    def test_schedule_withdrawal_endpoint_rejects_past_execute_at(self):
        execute_at = (timezone.now() - timedelta(minutes=1)).isoformat()

        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/withdrawals/",
            {"amount": 100, "execute_at": execute_at},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], 400)
        self.assertIn("detail", response.data)

    def test_schedule_withdrawal_endpoint_is_idempotent_with_header_key(self):
        execute_at = (timezone.now() + timedelta(minutes=30)).isoformat()
        path = f"/api/wallets/{self.wallet.id}/withdrawals/"

        first = self.client.post(
            path,
            {"amount": 220, "execute_at": execute_at},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-withdraw-001",
        )
        second = self.client.post(
            path,
            {"amount": 220, "execute_at": execute_at},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-withdraw-001",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["status"], 201)
        self.assertEqual(second.data["status"], 200)
        self.assertEqual(
            first.data["data"]["transaction"]["id"],
            second.data["data"]["transaction"]["id"],
        )
        self.assertEqual(
            Transaction.objects.filter(idempotency_key="api-withdraw-001").count(),
            1,
        )

    def test_schedule_withdrawal_endpoint_rejects_idempotency_payload_conflict(self):
        execute_at = (timezone.now() + timedelta(minutes=30)).isoformat()
        path = f"/api/wallets/{self.wallet.id}/withdrawals/"

        first = self.client.post(
            path,
            {"amount": 120, "execute_at": execute_at},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-withdraw-002",
        )
        second = self.client.post(
            path,
            {"amount": 130, "execute_at": execute_at},
            format="json",
            HTTP_IDEMPOTENCY_KEY="api-withdraw-002",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data["status"], 409)

    def test_schedule_withdrawal_endpoint_rejects_idempotency_header_body_mismatch(
        self,
    ):
        execute_at = (timezone.now() + timedelta(minutes=30)).isoformat()
        path = f"/api/wallets/{self.wallet.id}/withdrawals/"

        response = self.client.post(
            path,
            {
                "amount": 180,
                "execute_at": execute_at,
                "idempotency_key": "body-key",
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="header-key",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], 400)
        self.assertIn("detail", response.data)

    def test_wallet_not_found_uses_consistent_envelope(self):
        response = self.client.post(
            "/api/wallets/999999/deposit/",
            {"amount": 100},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["status"], 404)
        self.assertIn("message", response.data)
        self.assertIn("data", response.data)

    def test_parse_error_uses_consistent_envelope(self):
        response = self.client.post(
            f"/api/wallets/{self.wallet.id}/deposit/",
            data='{"amount":',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], 400)
        self.assertIn("detail", response.data)
        self.assertIn("message", response.data)
        self.assertIn("data", response.data)

    def test_method_not_allowed_uses_consistent_envelope(self):
        response = self.client.get(f"/api/wallets/{self.wallet.id}/deposit/")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.data["status"], 405)
        self.assertIn("detail", response.data)
        self.assertIn("message", response.data)
