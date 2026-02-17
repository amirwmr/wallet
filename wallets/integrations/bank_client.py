import logging
import time
from dataclasses import dataclass
from enum import Enum

from django.conf import settings

from wallets.integrations.http import HttpClient, NetworkRequestFailed
from wallets.integrations.rate_limiter import (
    RateLimiterUnavailable,
    build_rate_limiter,
)
from wallets.integrations.retry import full_jitter_delay, parse_retry_after_seconds

logger = logging.getLogger(__name__)


class TransferOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FINAL_FAILURE = "FINAL_FAILURE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TransferResult:
    outcome: TransferOutcome
    reference: str | None = None
    error_reason: str | None = None
    retry_after_seconds: float | None = None

    def __post_init__(self):
        if not isinstance(self.outcome, TransferOutcome):
            object.__setattr__(self, "outcome", TransferOutcome(self.outcome))

    @property
    def success(self):
        return self.outcome == TransferOutcome.SUCCESS

    @property
    def is_final_failure(self):
        return self.outcome == TransferOutcome.FINAL_FAILURE

    @property
    def is_unknown(self):
        return self.outcome == TransferOutcome.UNKNOWN

    @classmethod
    def succeeded(cls, *, reference):
        return cls(
            outcome=TransferOutcome.SUCCESS,
            reference=reference,
            error_reason=None,
        )

    @classmethod
    def final_failure(cls, *, error_reason, retry_after_seconds=None):
        return cls(
            outcome=TransferOutcome.FINAL_FAILURE,
            reference=None,
            error_reason=error_reason,
            retry_after_seconds=retry_after_seconds,
        )

    @classmethod
    def unknown(cls, *, error_reason):
        return cls(
            outcome=TransferOutcome.UNKNOWN,
            reference=None,
            error_reason=error_reason,
        )


class BankGateway:
    def __init__(self, *, base_url=None, http_client=None, rate_limiter=None):
        self.base_url = (base_url or settings.BANK_BASE_URL).rstrip("/")
        self.http_client = http_client or HttpClient(
            connect_timeout=settings.BANK_TIMEOUT,
            read_timeout=settings.BANK_TIMEOUT,
            max_attempts=1,
            retry_base_delay=0.0,
            retry_max_delay=0.0,
        )
        self.max_attempts = settings.BANK_RETRY_MAX_ATTEMPTS
        self.base_delay = settings.BANK_RETRY_BASE_DELAY
        self.max_delay = settings.BANK_RETRY_MAX_DELAY
        self.status_url_template = settings.BANK_STATUS_URL_TEMPLATE
        self.rate_limiter = rate_limiter or build_rate_limiter()

    def _acquire_rate_limit(self, *, idempotency_key, transfer_id):
        try:
            acquire_result = self.rate_limiter.acquire(cost=1)
        except RateLimiterUnavailable:
            logger.warning(
                "event=bank_rate_limit_unavailable worker_role=sender transfer_id=%s idempotency_key=%s limiter_wait_ms=0",
                transfer_id,
                idempotency_key,
            )
            return 0.0

        wait_seconds = acquire_result.wait_seconds
        wait_ms = int(wait_seconds * 1000)
        if wait_ms > 0:
            logger.warning(
                "event=bank_rate_limit_wait worker_role=sender transfer_id=%s idempotency_key=%s limiter_wait_ms=%s",
                transfer_id,
                idempotency_key,
                wait_ms,
            )
        return wait_seconds

    def _compute_retry_delay(self, *, attempt, retry_after_seconds):
        backoff_delay = full_jitter_delay(
            attempt,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
        )
        if retry_after_seconds is None:
            return backoff_delay
        return max(backoff_delay, retry_after_seconds)

    def transfer(
        self,
        idempotency_key,
        wallet_owner_ref=None,
        amount=None,
        *,
        transfer_id=None,
    ):
        transfer_id = transfer_id or idempotency_key
        logger.info(
            "event=bank_transfer_request worker_role=sender transfer_id=%s idempotency_key=%s wallet_owner_ref=%s amount=%s",
            transfer_id,
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

        for attempt in range(1, self.max_attempts + 1):
            self._acquire_rate_limit(
                idempotency_key=idempotency_key,
                transfer_id=transfer_id,
            )
            try:
                response = self.http_client.post_json(
                    url, json=payload, headers=headers
                )
            except NetworkRequestFailed:
                if attempt < self.max_attempts:
                    delay = self._compute_retry_delay(
                        attempt=attempt,
                        retry_after_seconds=None,
                    )
                    logger.warning(
                        "event=bank_transfer_retry worker_role=sender transfer_id=%s idempotency_key=%s reason=network_error attempt=%s delay_ms=%s",
                        transfer_id,
                        idempotency_key,
                        attempt,
                        int(delay * 1000),
                    )
                    if delay > 0:
                        logger.info(
                            "event=bank_transfer_retry_wait worker_role=sender transfer_id=%s idempotency_key=%s limiter_wait_ms=%s",
                            transfer_id,
                            idempotency_key,
                            int(delay * 1000),
                        )
                        time.sleep(delay)
                    continue
                logger.warning(
                    "event=bank_transfer_unknown worker_role=sender transfer_id=%s idempotency_key=%s reason=network_error",
                    transfer_id,
                    idempotency_key,
                )
                return TransferResult.unknown(error_reason="network_error")

            logger.info(
                "event=bank_transfer_http_response worker_role=sender transfer_id=%s idempotency_key=%s http_status=%s",
                transfer_id,
                idempotency_key,
                response.status_code,
            )

            if response.status_code == 429:
                retry_after_seconds = parse_retry_after_seconds(
                    response.headers.get("Retry-After")
                )
                if attempt < self.max_attempts:
                    delay = self._compute_retry_delay(
                        attempt=attempt,
                        retry_after_seconds=retry_after_seconds,
                    )
                    logger.warning(
                        "event=bank_transfer_retry worker_role=sender transfer_id=%s idempotency_key=%s reason=rate_limited attempt=%s retry_after_seconds=%s delay_ms=%s",
                        transfer_id,
                        idempotency_key,
                        attempt,
                        retry_after_seconds,
                        int(delay * 1000),
                    )
                    if delay > 0:
                        logger.info(
                            "event=bank_transfer_retry_wait worker_role=sender transfer_id=%s idempotency_key=%s limiter_wait_ms=%s",
                            transfer_id,
                            idempotency_key,
                            int(delay * 1000),
                        )
                        time.sleep(delay)
                    continue
                return TransferResult.final_failure(
                    error_reason="rate_limited",
                    retry_after_seconds=retry_after_seconds,
                )

            result = self._normalize_response(
                response,
                fallback_reference=idempotency_key,
            )
            if result.success:
                logger.info(
                    "event=bank_transfer_success worker_role=sender transfer_id=%s idempotency_key=%s reference=%s",
                    transfer_id,
                    idempotency_key,
                    result.reference,
                )
            elif result.is_final_failure:
                logger.warning(
                    "event=bank_transfer_failed worker_role=sender transfer_id=%s idempotency_key=%s reason=%s",
                    transfer_id,
                    idempotency_key,
                    result.error_reason,
                )
            else:
                logger.warning(
                    "event=bank_transfer_unknown worker_role=sender transfer_id=%s idempotency_key=%s reason=%s",
                    transfer_id,
                    idempotency_key,
                    result.error_reason,
                )
            return result

        return TransferResult.unknown(error_reason="retry_exhausted")

    def can_query_status(self):
        return bool(self.status_url_template)

    def query_transfer_status(
        self, *, idempotency_key, transfer_id=None, reference=None
    ):
        transfer_id = transfer_id or idempotency_key
        if not self.can_query_status():
            return TransferResult.unknown(error_reason="status_endpoint_not_configured")

        url = self.status_url_template.format(
            idempotency_key=idempotency_key,
            reference=reference or "",
        )
        headers = {"X-Idempotency-Key": idempotency_key}

        for attempt in range(1, self.max_attempts + 1):
            self._acquire_rate_limit(
                idempotency_key=idempotency_key,
                transfer_id=transfer_id,
            )
            try:
                response = self.http_client.get_json(url, headers=headers)
            except NetworkRequestFailed:
                if attempt < self.max_attempts:
                    delay = self._compute_retry_delay(
                        attempt=attempt,
                        retry_after_seconds=None,
                    )
                    if delay > 0:
                        time.sleep(delay)
                    continue
                return TransferResult.unknown(error_reason="status_query_network_error")

            if response.status_code == 429:
                retry_after_seconds = parse_retry_after_seconds(
                    response.headers.get("Retry-After")
                )
                if attempt < self.max_attempts:
                    delay = self._compute_retry_delay(
                        attempt=attempt,
                        retry_after_seconds=retry_after_seconds,
                    )
                    if delay > 0:
                        time.sleep(delay)
                    continue
                return TransferResult.unknown(error_reason="status_query_rate_limited")

            return self._normalize_response(
                response,
                fallback_reference=reference or idempotency_key,
            )

        return TransferResult.unknown(error_reason="status_query_retry_exhausted")

    @staticmethod
    def _normalize_response(response, *, fallback_reference):
        try:
            body = response.json()
        except ValueError:
            return TransferResult.unknown(
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
            return TransferResult.succeeded(reference=reference)

        failure_reason = (
            body.get("error_reason")
            or body_state
            or f"upstream_status_{normalized_status}"
        )
        if response.status_code >= 500:
            return TransferResult.unknown(error_reason=str(failure_reason))
        return TransferResult.final_failure(error_reason=str(failure_reason))
