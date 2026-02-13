from unittest.mock import Mock

from django.test import SimpleTestCase

from wallets.integrations.bank_client import BankGateway
from wallets.integrations.http import NetworkRequestFailed


class BankGatewayTests(SimpleTestCase):
    def test_transfer_success_is_normalized(self):
        http_client = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "data": "success",
            "status": 200,
            "reference": "bank-ref-123",
        }
        http_client.post_json.return_value = response

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(
            idempotency_key="idem-key-1",
            wallet_owner_ref="wallet-1",
            amount=250,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.reference, "bank-ref-123")
        self.assertIsNone(result.error_reason)
        http_client.post_json.assert_called_once()

    def test_transfer_failure_response_is_normalized(self):
        http_client = Mock()
        response = Mock()
        response.status_code = 503
        response.json.return_value = {
            "data": "failed",
            "status": 503,
        }
        http_client.post_json.return_value = response

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-key-2", amount=100)

        self.assertFalse(result.success)
        self.assertIsNone(result.reference)
        self.assertEqual(result.error_reason, "failed")

    def test_transfer_uses_idempotency_key_as_reference_when_missing(self):
        http_client = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "data": "success",
            "status": "200",
        }
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

        self.assertFalse(result.success)
        self.assertEqual(result.error_reason, "network_error")

    def test_transfer_invalid_json_returns_failure(self):
        http_client = Mock()
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("invalid json")
        http_client.post_json.return_value = response

        gateway = BankGateway(base_url="http://bank.local", http_client=http_client)
        result = gateway.transfer(idempotency_key="idem-key-4", amount=100)

        self.assertFalse(result.success)
        self.assertIsNone(result.reference)
        self.assertIn("invalid_json_response", result.error_reason)
