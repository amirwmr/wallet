import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from wallets.integrations.http import HttpClient, NetworkRequestFailed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransferResult:
    success: bool
    reference: Optional[str] = None
    error_reason: Optional[str] = None


class BankGateway:
    def __init__(self, *, base_url=None, http_client=None):
        self.base_url = (base_url or settings.BANK_BASE_URL).rstrip("/")
        self.http_client = http_client or HttpClient(
            connect_timeout=settings.BANK_TIMEOUT,
            read_timeout=settings.BANK_TIMEOUT,
            max_retries=settings.BANK_RETRY_COUNT,
        )

    def transfer(self, idempotency_key, wallet_owner_ref=None, amount=None):
        logger.info(
            "event=bank_transfer_request idempotency_key=%s wallet_owner_ref=%s amount=%s",
            idempotency_key,
            wallet_owner_ref,
            amount,
        )
        payload = {
            "idempotency_key": idempotency_key,
            "wallet_owner_ref": wallet_owner_ref,
            "amount": amount,
        }
        headers = {
            "X-Idempotency-Key": idempotency_key,
        }
        url = f"{self.base_url}/"

        try:
            response = self.http_client.post_json(url, json=payload, headers=headers)
        except NetworkRequestFailed:
            logger.warning(
                "event=bank_transfer_network_failure idempotency_key=%s",
                idempotency_key,
            )
            return TransferResult(
                success=False,
                reference=None,
                error_reason="network_error",
            )
        logger.info(
            "event=bank_transfer_http_response idempotency_key=%s http_status=%s",
            idempotency_key,
            response.status_code,
        )
        result = self._normalize_response(response, fallback_reference=idempotency_key)
        if result.success:
            logger.info(
                "event=bank_transfer_success idempotency_key=%s reference=%s",
                idempotency_key,
                result.reference,
            )
        else:
            logger.warning(
                "event=bank_transfer_failed idempotency_key=%s reason=%s",
                idempotency_key,
                result.error_reason,
            )
        return result

    @staticmethod
    def _normalize_response(response, *, fallback_reference):
        try:
            body = response.json()
        except ValueError:
            return TransferResult(
                success=False,
                reference=None,
                error_reason=f"invalid_json_response_http_{response.status_code}",
            )

        response_status = body.get("status", response.status_code)
        try:
            normalized_status = int(response_status)
        except (TypeError, ValueError):
            normalized_status = response.status_code
        body_state = body.get("data")
        http_success = 200 <= response.status_code < 300

        if http_success and normalized_status == 200 and body_state == "success":
            reference = (
                body.get("reference")
                or body.get("bank_reference")
                or body.get("transfer_id")
                or fallback_reference
            )
            return TransferResult(success=True, reference=reference, error_reason=None)

        failure_reason = (
            body.get("error_reason")
            or body_state
            or f"upstream_status_{normalized_status}"
        )
        return TransferResult(
            success=False, reference=None, error_reason=str(failure_reason)
        )
