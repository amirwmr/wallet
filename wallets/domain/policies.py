from datetime import datetime

from django.utils import timezone

from wallets.domain.exceptions import InvalidAmount, InvalidExecuteAt


def validate_positive_amount(amount):
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidAmount("amount must be a positive integer in minor units")

    if amount <= 0:
        raise InvalidAmount("amount must be greater than zero")

    return amount


def validate_future_execute_at(execute_at, now=None):
    if not isinstance(execute_at, datetime):
        raise InvalidExecuteAt("execute_at must be a datetime")

    if timezone.is_naive(execute_at):
        raise InvalidExecuteAt("execute_at must be timezone-aware")

    now_value = now or timezone.now()
    if execute_at <= now_value:
        raise InvalidExecuteAt("execute_at must be in the future")

    return execute_at
