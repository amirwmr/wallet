def retry_on_exceptions(func, *, exceptions, max_retries):
    """
    Retry `func` for selected exceptions.

    `max_retries` means retries after the first attempt.
    """
    attempts = 0
    while True:
        try:
            return func()
        except exceptions:
            if attempts >= max_retries:
                raise
            attempts += 1
