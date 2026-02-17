import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from wallets.integrations.bank_client import BankGateway, TransferOutcome
from wallets.models import Transaction, Wallet, WithdrawalReconciliationTask
from wallets.tasks.execute_withdrawals import (
    _mark_unknown_and_queue_reconciliation,
    _with_execution_lock,
)

logger = logging.getLogger(__name__)


def _resolve_unknown_task(task, bank_gateway):
    with transaction.atomic():
        locked_task = (
            WithdrawalReconciliationTask.objects.select_for_update()
            .select_related("transaction")
            .get(pk=task.pk)
        )
        tx = Transaction.objects.select_for_update().get(pk=locked_task.transaction_id)
        wallet = Wallet.objects.select_for_update().get(pk=tx.wallet_id)

        if locked_task.status != WithdrawalReconciliationTask.Status.PENDING:
            return "skipped"

        if tx.status == Transaction.Status.SUCCEEDED:
            locked_task.status = WithdrawalReconciliationTask.Status.RESOLVED
            locked_task.reason = "ALREADY_SUCCEEDED"
            locked_task.save(update_fields=["status", "reason", "updated_at"])
            return "resolved"

        if tx.status == Transaction.Status.FAILED:
            locked_task.status = WithdrawalReconciliationTask.Status.RESOLVED
            locked_task.reason = "ALREADY_FAILED"
            locked_task.save(update_fields=["status", "reason", "updated_at"])
            return "resolved"

        if tx.status not in {Transaction.Status.UNKNOWN, Transaction.Status.PROCESSING}:
            return "skipped"

        if not bank_gateway.can_query_status():
            logger.warning(
                "event=reconciler_status_endpoint_missing worker_role=reconciler tx_id=%s idempotency_key=%s",
                tx.id,
                tx.idempotency_key,
            )
            return "pending"

        status_result = bank_gateway.query_transfer_status(
            idempotency_key=tx.idempotency_key,
            transfer_id=tx.id,
            reference=tx.external_reference or tx.bank_reference,
        )

        if status_result.outcome == TransferOutcome.SUCCESS:
            tx.status = Transaction.Status.SUCCEEDED
            tx.external_reference = status_result.reference
            tx.bank_reference = status_result.reference
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
            locked_task.status = WithdrawalReconciliationTask.Status.RESOLVED
            locked_task.reason = "RECONCILED_SUCCESS"
            locked_task.save(update_fields=["status", "reason", "updated_at"])
            logger.info(
                "event=reconciler_resolved_success worker_role=reconciler tx_id=%s idempotency_key=%s reference=%s",
                tx.id,
                tx.idempotency_key,
                status_result.reference,
            )
            return "resolved_success"

        if status_result.outcome == TransferOutcome.FINAL_FAILURE:
            Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") + tx.amount)
            tx.status = Transaction.Status.FAILED
            tx.failure_reason = status_result.error_reason or "RECONCILED_FINAL_FAILURE"
            tx.save(update_fields=["status", "failure_reason", "updated_at"])
            locked_task.status = WithdrawalReconciliationTask.Status.RESOLVED
            locked_task.reason = "RECONCILED_FINAL_FAILURE"
            locked_task.save(update_fields=["status", "reason", "updated_at"])
            logger.warning(
                "event=reconciler_resolved_final_failure worker_role=reconciler tx_id=%s idempotency_key=%s reason=%s",
                tx.id,
                tx.idempotency_key,
                tx.failure_reason,
            )
            return "resolved_failure"

        logger.warning(
            "event=reconciler_still_unknown worker_role=reconciler tx_id=%s idempotency_key=%s reason=%s",
            tx.id,
            tx.idempotency_key,
            status_result.error_reason,
        )
        return "pending"


def _mark_stale_processing_unknown(now, *, timeout_seconds, limit):
    stale_before = now - timedelta(seconds=timeout_seconds)
    processed = 0

    while processed < limit:
        queryset = Transaction.objects.filter(
            type=Transaction.Type.WITHDRAWAL,
            status=Transaction.Status.PROCESSING,
            updated_at__lte=stale_before,
        ).order_by("updated_at", "id")

        with transaction.atomic():
            tx = _with_execution_lock(queryset).first()
            if tx is None:
                break

            _mark_unknown_and_queue_reconciliation(
                tx,
                reason="PROCESSING_TIMEOUT_RECONCILIATION_REQUIRED",
            )
            processed += 1

    return processed


def reconcile_withdrawals(limit=100, now=None, *, gateway=None):
    now = now or timezone.now()
    if limit <= 0:
        return {
            "stale_marked_unknown": 0,
            "resolved_success": 0,
            "resolved_failure": 0,
            "pending": 0,
            "resolved": 0,
        }

    bank_gateway = gateway or BankGateway()
    timeout_seconds = settings.WITHDRAWAL_PROCESSING_TIMEOUT_SECONDS

    stale_marked_unknown = _mark_stale_processing_unknown(
        now,
        timeout_seconds=timeout_seconds,
        limit=limit,
    )

    resolved_success = 0
    resolved_failure = 0
    resolved = 0
    pending = 0

    pending_tasks = (
        WithdrawalReconciliationTask.objects.filter(
            status=WithdrawalReconciliationTask.Status.PENDING
        )
        .select_related("transaction")
        .order_by("created_at", "id")[:limit]
    )

    for task in pending_tasks:
        result = _resolve_unknown_task(task, bank_gateway)
        if result == "resolved_success":
            resolved_success += 1
        elif result == "resolved_failure":
            resolved_failure += 1
        elif result == "resolved":
            resolved += 1
        elif result == "pending":
            pending += 1

    summary = {
        "stale_marked_unknown": stale_marked_unknown,
        "resolved_success": resolved_success,
        "resolved_failure": resolved_failure,
        "pending": pending,
        "resolved": resolved,
    }
    logger.info(
        "event=reconciler_end worker_role=reconciler stale_marked_unknown=%s resolved_success=%s resolved_failure=%s pending=%s resolved=%s",
        summary["stale_marked_unknown"],
        summary["resolved_success"],
        summary["resolved_failure"],
        summary["pending"],
        summary["resolved"],
    )
    return summary
