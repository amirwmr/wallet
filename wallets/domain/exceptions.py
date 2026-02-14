class DomainError(Exception):
    """Base class for domain-layer errors."""


class WalletNotFound(DomainError):
    """Raised when target wallet does not exist."""


class InvalidAmount(DomainError):
    """Raised when amount is not a positive integer."""


class InvalidExecuteAt(DomainError):
    """Raised when execute_at is invalid or not in the future."""


class InvalidTransactionState(DomainError):
    """Raised when transaction transition is not allowed."""


class InvalidIdempotencyKey(DomainError):
    """Raised when idempotency key format/value is invalid."""


class IdempotencyConflict(DomainError):
    """Raised when idempotency key is reused with a different payload."""
