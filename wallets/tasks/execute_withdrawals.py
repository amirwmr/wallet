import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone

from wallets.integrations.bank_client import (
    BankGateway,
    TransferOutcome,
    TransferResult,
)
from wallets.integrations.idempotency import ensure_transaction_idempotency_key
from wallets.models import Transaction, Wallet, WithdrawalReconciliationTask

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedWithdrawal:
    transaction_id: int
    wallet_owner_ref: str
    amount: int
    idempotency_key: str


def _with_execution_lock(queryset):
    if connection.features.has_select_for_update:
        if connection.features.has_select_for_update_skip_locked:
            return queryset.select_for_update(skip_locked=True)
        return queryset.select_for_update()
    return queryset


def _queue_reconciliation_task(transaction, *, reason):
    task, created = WithdrawalReconciliationTask.objects.get_or_create(
        transaction=transaction,
        defaults={"reason": reason},
    )
    return task, created


def _mark_unknown_and_queue_reconciliation(transaction, *, reason):
    transaction.status = Transaction.Status.UNKNOWN
    transaction.failure_reason = reason
    transaction.save(update_fields=["status", "failure_reason", "updated_at"])
    task, created = _queue_reconciliation_task(
        transaction,
        reason="UNKNOWN_TRANSFER_OUTCOME",
    )
    logger.warning(
        "event=withdrawal_marked_unknown worker_role=executor tx_id=%s idempotency_key=%s reason=%s reconciliation_task_id=%s reconciliation_created=%s",
        transaction.id,
        transaction.idempotency_key,
        reason,
        task.id,
        created,
    )
    return task, created


def _claim_next_due_withdrawal(now):
    queryset = Transaction.objects.filter(
        type=Transaction.Type.WITHDRAWAL,
        status=Transaction.Status.SCHEDULED,
        execute_at__lte=now,
    ).order_by("execute_at", "id")

    with transaction.atomic():
        tx = _with_execution_lock(queryset).select_related("wallet").first()
        if tx is None:
            return None

        wallet = Wallet.objects.select_for_update().get(pk=tx.wallet_id)
        debited = Wallet.objects.filter(pk=wallet.pk, balance__gte=tx.amount).update(
            balance=F("balance") - tx.amount
        )
        if debited == 0:
            tx.status = Transaction.Status.FAILED
            tx.failure_reason = "INSUFFICIENT_FUNDS"
            tx.save(update_fields=["status", "failure_reason", "updated_at"])
            logger.info(
                "event=withdrawal_failed_insufficient_funds worker_role=executor tx_id=%s idempotency_key=%s wallet_id=%s amount=%s",
                tx.id,
                tx.idempotency_key,
                tx.wallet_id,
                tx.amount,
            )
            return {"outcome": "insufficient_funds", "transaction_id": tx.id}

        tx.idempotency_key = ensure_transaction_idempotency_key(tx)
        tx.status = Transaction.Status.PROCESSING
        tx.failure_reason = None
        tx.save(
            update_fields=["idempotency_key", "status", "failure_reason", "updated_at"]
        )
        logger.info(
            "event=withdrawal_claimed worker_role=executor tx_id=%s wallet_id=%s amount=%s idempotency_key=%s claim_type=scheduled",
            tx.id,
            tx.wallet_id,
            tx.amount,
            tx.idempotency_key,
        )

        return {
            "outcome": "claimed",
            "claim": ClaimedWithdrawal(
                transaction_id=tx.id,
                wallet_owner_ref=str(wallet.uuid),
                amount=tx.amount,
                idempotency_key=tx.idempotency_key,
            ),
        }


def _claim_stale_processing_withdrawal(now, *, stale_after_seconds):
    stale_before = now - timedelta(seconds=stale_after_seconds)
    queryset = Transaction.objects.filter(
        type=Transaction.Type.WITHDRAWAL,
        status=Transaction.Status.PROCESSING,
        updated_at__lte=stale_before,
    ).order_by("updated_at", "id")

    with transaction.atomic():
        tx = _with_execution_lock(queryset).select_related("wallet").first()
        if tx is None:
            return None

        tx.idempotency_key = ensure_transaction_idempotency_key(tx)
        tx.failure_reason = None
        tx.save(update_fields=["idempotency_key", "failure_reason", "updated_at"])

        logger.warning(
            "event=withdrawal_reclaimed_processing worker_role=executor tx_id=%s wallet_id=%s idempotency_key=%s",
            tx.id,
            tx.wallet_id,
            tx.idempotency_key,
        )
        return {
            "outcome": "claimed",
            "claim": ClaimedWithdrawal(
                transaction_id=tx.id,
                wallet_owner_ref=str(tx.wallet.uuid),
                amount=tx.amount,
                idempotency_key=tx.idempotency_key,
            ),
        }


def _queue_stale_processing_for_reconciliation(now, *, stale_after_seconds):
    stale_before = now - timedelta(seconds=stale_after_seconds)
    queryset = Transaction.objects.filter(
        type=Transaction.Type.WITHDRAWAL,
        status=Transaction.Status.PROCESSING,
        updated_at__lte=stale_before,
    ).order_by("updated_at", "id")

    with transaction.atomic():
        tx = _with_execution_lock(queryset).first()
        if tx is None:
            return None

        task, created = _mark_unknown_and_queue_reconciliation(
            tx,
            reason="RECONCILIATION_REQUIRED",
        )
        if created:
            task.reason = "STALE_PROCESSING_WITHOUT_BANK_IDEMPOTENCY"
            task.save(update_fields=["reason", "updated_at"])

        logger.warning(
            "event=withdrawal_reconciliation_queued worker_role=executor tx_id=%s idempotency_key=%s wallet_id=%s queue_created=%s task_id=%s",
            tx.id,
            tx.idempotency_key,
            tx.wallet_id,
            created,
            task.id,
        )
        return {"outcome": "reconciliation_queued", "transaction_id": tx.id}


def _finalize_claimed_withdrawal(claim, transfer_result):
    with transaction.atomic():
        tx = Transaction.objects.select_for_update().get(pk=claim.transaction_id)
        wallet = Wallet.objects.select_for_update().get(pk=tx.wallet_id)

        if tx.status != Transaction.Status.PROCESSING:
            logger.info(
                "event=withdrawal_finalize_skipped worker_role=executor tx_id=%s idempotency_key=%s current_status=%s",
                tx.id,
                tx.idempotency_key,
                tx.status,
            )
            return "skipped"

        if transfer_result.outcome == TransferOutcome.SUCCESS:
            tx.status = Transaction.Status.SUCCEEDED
            tx.external_reference = transfer_result.reference
            tx.bank_reference = transfer_result.reference
            tx.failure_reason = None
            tx.save(
                update_fields=[
                    "status",
                    "external_reference",
                    "bank_reference",
                    "failure_reason",
                    "updated_at",
                ]
            )
            logger.info(
                "event=withdrawal_succeeded worker_role=executor tx_id=%s idempotency_key=%s wallet_id=%s reference=%s",
                tx.id,
                tx.idempotency_key,
                tx.wallet_id,
                transfer_result.reference,
            )
            return "succeeded"

        if transfer_result.outcome == TransferOutcome.UNKNOWN:
            _mark_unknown_and_queue_reconciliation(
                tx,
                reason=transfer_result.error_reason or "UNKNOWN_TRANSFER_OUTCOME",
            )
            return "unknown"

        Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") + tx.amount)
        tx.status = Transaction.Status.FAILED
        tx.failure_reason = transfer_result.error_reason or "BANK_TRANSFER_FAILED"
        tx.save(update_fields=["status", "failure_reason", "updated_at"])
        logger.warning(
            "event=withdrawal_failed_refunded worker_role=executor tx_id=%s idempotency_key=%s wallet_id=%s reason=%s amount=%s",
            tx.id,
            tx.idempotency_key,
            tx.wallet_id,
            tx.failure_reason,
            tx.amount,
        )
        return "failed"


def execute_due_withdrawals(limit=100, now=None, *, gateway=None):
    now = now or timezone.now()

    if limit <= 0:
        return {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "insufficient_funds": 0,
            "reconciliation_queued": 0,
            "unknown": 0,
        }

    bank_gateway = gateway or BankGateway()
    stale_after_seconds = settings.WITHDRAWAL_PROCESSING_STALE_SECONDS
    max_lock_contention_retries = settings.EXECUTOR_LOCK_CONTENTION_MAX_RETRIES
    lock_contention_backoff_seconds = settings.EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS
    bank_honors_idempotency = settings.BANK_HONORS_IDEMPOTENCY
    logger.info(
        "event=executor_start limit=%s now=%s stale_after_seconds=%s max_lock_contention_retries=%s lock_contention_backoff_seconds=%s bank_honors_idempotency=%s",
        limit,
        now.isoformat(),
        stale_after_seconds,
        max_lock_contention_retries,
        lock_contention_backoff_seconds,
        bank_honors_idempotency,
    )

    processed = 0
    succeeded = 0
    failed = 0
    insufficient_funds = 0
    reconciliation_queued = 0
    unknown = 0
    lock_contention_retries = 0

    while processed < limit:
        try:
            claim_result = _claim_next_due_withdrawal(now)
            if claim_result is None:
                if bank_honors_idempotency:
                    claim_result = _claim_stale_processing_withdrawal(
                        now,
                        stale_after_seconds=stale_after_seconds,
                    )
                else:
                    claim_result = _queue_stale_processing_for_reconciliation(
                        now,
                        stale_after_seconds=stale_after_seconds,
                    )
        except OperationalError:
            lock_contention_retries += 1
            logger.warning(
                "event=executor_lock_contention limit=%s retry=%s max_lock_contention_retries=%s",
                limit,
                lock_contention_retries,
                max_lock_contention_retries,
            )
            if lock_contention_retries > max_lock_contention_retries:
                logger.warning(
                    "event=executor_lock_contention_exhausted limit=%s retries=%s",
                    limit,
                    lock_contention_retries,
                )
                break
            if lock_contention_backoff_seconds > 0:
                time.sleep(lock_contention_backoff_seconds)
            continue

        if claim_result is None:
            break
        lock_contention_retries = 0

        outcome = claim_result["outcome"]
        if outcome == "insufficient_funds":
            processed += 1
            failed += 1
            insufficient_funds += 1
            continue
        if outcome == "reconciliation_queued":
            processed += 1
            reconciliation_queued += 1
            continue

        claim = claim_result["claim"]
        logger.info(
            "event=withdrawal_execution_start worker_role=executor tx_id=%s idempotency_key=%s wallet_owner_ref=%s amount=%s",
            claim.transaction_id,
            claim.idempotency_key,
            claim.wallet_owner_ref,
            claim.amount,
        )

        try:
            transfer_result = bank_gateway.transfer(
                idempotency_key=claim.idempotency_key,
                wallet_owner_ref=claim.wallet_owner_ref,
                amount=claim.amount,
                transfer_id=claim.transaction_id,
            )
        except Exception as exc:
            transfer_result = TransferResult.unknown(
                error_reason=f"gateway_exception:{exc.__class__.__name__}",
            )
            logger.exception(
                "event=executor_gateway_exception worker_role=executor tx_id=%s idempotency_key=%s error=%s",
                claim.transaction_id,
                claim.idempotency_key,
                exc.__class__.__name__,
            )

        finalize_result = _finalize_claimed_withdrawal(claim, transfer_result)
        if finalize_result == "succeeded":
            succeeded += 1
            processed += 1
        elif finalize_result == "failed":
            failed += 1
            processed += 1
        elif finalize_result == "unknown":
            unknown += 1
            reconciliation_queued += 1
            processed += 1

    summary = {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "insufficient_funds": insufficient_funds,
        "reconciliation_queued": reconciliation_queued,
        "unknown": unknown,
    }
    logger.info(
        "event=executor_end worker_role=executor processed=%s succeeded=%s failed=%s insufficient_funds=%s reconciliation_queued=%s unknown=%s",
        summary["processed"],
        summary["succeeded"],
        summary["failed"],
        summary["insufficient_funds"],
        summary["reconciliation_queued"],
        summary["unknown"],
    )
    return summary
