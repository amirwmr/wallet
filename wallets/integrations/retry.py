import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def full_jitter_delay(attempt, *, base_delay, max_delay):
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    if base_delay < 0 or max_delay < 0:
        raise ValueError("base_delay and max_delay must be >= 0")

    cap = min(max_delay, base_delay * (2 ** (attempt - 1)))
    return random.uniform(0, cap)


def parse_retry_after_seconds(value):
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        retry_seconds = float(raw)
        return max(0.0, retry_seconds)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return max(0.0, (retry_at - now).total_seconds())


def retry_on_exceptions(
    func,
    *,
    exceptions,
    max_attempts,
    base_delay,
    max_delay,
    on_retry=None,
    sleep=time.sleep,
):
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    attempt = 1
    while True:
        try:
            return func()
        except exceptions as exc:
            if attempt >= max_attempts:
                raise

            delay = full_jitter_delay(
                attempt,
                base_delay=base_delay,
                max_delay=max_delay,
            )
            if on_retry is not None:
                on_retry(attempt=attempt, delay_seconds=delay, exception=exc)
            if delay > 0:
                sleep(delay)
            attempt += 1
