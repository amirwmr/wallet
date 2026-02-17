from unittest.mock import Mock

from django.test import SimpleTestCase

from wallets.integrations.bank_client import BankGateway, TransferOutcome
from wallets.integrations.http import NetworkRequestFailed


class BankGatewayTests(SimpleTestCase):
    @staticmethod
    def _response(status_code, body, headers=None):
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        response.json.return_value = body
        return response

    def test_transfer_success_is_normalized(self):
        http_client = Mock()
        response = self._response(
            200,
            {
                "data": "success",
                "status": 200,
                "reference": "bank-ref-123",
            },
        )
        http_client.post_json.return_value = response

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(
            idempotency_key="idem-key-1",
            wallet_owner_ref="wallet-1",
            amount=250,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.outcome, TransferOutcome.SUCCESS)
        self.assertEqual(result.reference, "bank-ref-123")
        self.assertIsNone(result.error_reason)
        http_client.post_json.assert_called_once()

    def test_transfer_failure_response_is_normalized(self):
        http_client = Mock()
        response = self._response(
            400,
            {
                "data": "failed",
                "status": 400,
            },
        )
        http_client.post_json.return_value = response

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-key-2", amount=100)

        self.assertEqual(result.outcome, TransferOutcome.FINAL_FAILURE)
        self.assertIsNone(result.reference)
        self.assertEqual(result.error_reason, "failed")

    def test_transfer_uses_idempotency_key_as_reference_when_missing(self):
        http_client = Mock()
        response = self._response(
            200,
            {
                "data": "success",
                "status": "200",
            },
        )
        http_client.post_json.return_value = response

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-key-fallback", amount=100)

        self.assertTrue(result.success)
        self.assertEqual(result.reference, "idem-key-fallback")
        self.assertIsNone(result.error_reason)

    def test_transfer_network_failure_returns_network_error(self):
        http_client = Mock()
        http_client.post_json.side_effect = NetworkRequestFailed("boom")

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-key-3", amount=100)

        self.assertEqual(result.outcome, TransferOutcome.UNKNOWN)
        self.assertEqual(result.error_reason, "network_error")

    def test_transfer_timeout_maps_to_unknown(self):
        http_client = Mock()
        http_client.post_json.side_effect = NetworkRequestFailed("timeout")

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-timeout", amount=100)

        self.assertEqual(result.outcome, TransferOutcome.UNKNOWN)
        self.assertEqual(result.error_reason, "network_error")

    def test_transfer_connection_error_maps_to_unknown(self):
        http_client = Mock()
        http_client.post_json.side_effect = NetworkRequestFailed("connection_error")

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-connection", amount=100)

        self.assertEqual(result.outcome, TransferOutcome.UNKNOWN)
        self.assertEqual(result.error_reason, "network_error")

    def test_transfer_invalid_json_returns_failure(self):
        http_client = Mock()
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.json.side_effect = ValueError("invalid json")
        http_client.post_json.return_value = response

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-key-4", amount=100)

        self.assertEqual(result.outcome, TransferOutcome.UNKNOWN)
        self.assertIsNone(result.reference)
        self.assertIn("invalid_json_response", result.error_reason)

    def test_transfer_retries_on_429_then_succeeds(self):
        http_client = Mock()
        rate_limited = self._response(
            429,
            {"data": "failed", "status": 429},
            headers={"Retry-After": "0"},
        )
        success = self._response(
            200,
            {"data": "success", "status": 200, "reference": "ref-1"},
        )
        http_client.post_json.side_effect = [rate_limited, success]

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        gateway.max_attempts = 3
        gateway.base_delay = 0
        gateway.max_delay = 0

        result = gateway.transfer(idempotency_key="idem-key-5", amount=100)

        self.assertEqual(result.outcome, TransferOutcome.SUCCESS)
        self.assertEqual(result.reference, "ref-1")
        self.assertEqual(http_client.post_json.call_count, 2)

    def test_transfer_rate_limited_exhaustion_returns_final_failure(self):
        http_client = Mock()
        rate_limited = self._response(
            429,
            {"data": "failed", "status": 429},
            headers={"Retry-After": "0"},
        )
        http_client.post_json.side_effect = [rate_limited, rate_limited]

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        gateway.max_attempts = 2
        gateway.base_delay = 0
        gateway.max_delay = 0

        result = gateway.transfer(idempotency_key="idem-key-6", amount=100)

        self.assertEqual(result.outcome, TransferOutcome.FINAL_FAILURE)
        self.assertEqual(result.error_reason, "rate_limited")

    def test_transfer_uses_rate_limiter_acquire(self):
        http_client = Mock()
        response = self._response(200, {"data": "success", "status": 200})
        http_client.post_json.return_value = response

        limiter = Mock()
        limiter.acquire.return_value = Mock(wait_seconds=0.0, wait_events=0)

        gateway = BankGateway(
            base_url="http://bank.local",
            http_client=http_client,
            rate_limiter=limiter,
        )
        gateway.transfer(idempotency_key="idem-key-7", amount=100)

        limiter.acquire.assert_called()
