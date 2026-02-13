import uuid

from wallets.domain.constants import TransactionType
from wallets.models import Transaction


def generate_idempotency_key():
    return uuid.uuid4().hex


def ensure_transaction_idempotency_key(transaction):
    if transaction.type != TransactionType.WITHDRAWAL.value:
        raise ValueError("idempotency key is only used for withdrawal transactions")

    if transaction.idempotency_key:
        return transaction.idempotency_key

    for _ in range(3):
        candidate = generate_idempotency_key()
        exists = Transaction.objects.filter(idempotency_key=candidate).exists()
        if exists:
            continue

        updated = Transaction.objects.filter(
            pk=transaction.pk,
            idempotency_key__isnull=True,
        ).update(idempotency_key=candidate)
        if updated:
            transaction.idempotency_key = candidate
            return transaction.idempotency_key

        transaction.refresh_from_db(fields=["idempotency_key"])
        if transaction.idempotency_key:
            return transaction.idempotency_key

    raise RuntimeError("failed to generate a unique idempotency key")
