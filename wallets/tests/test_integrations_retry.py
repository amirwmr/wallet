from unittest.mock import Mock

from django.test import SimpleTestCase

from wallets.integrations.retry import (
    full_jitter_delay,
    parse_retry_after_seconds,
    retry_on_exceptions,
)


class RetryHelpersTests(SimpleTestCase):
    def test_full_jitter_delay_is_bounded(self):
        delay = full_jitter_delay(3, base_delay=0.2, max_delay=1.0)
        self.assertGreaterEqual(delay, 0)
        self.assertLessEqual(delay, 0.8)

    def test_parse_retry_after_seconds_for_integer(self):
        self.assertEqual(parse_retry_after_seconds("2"), 2.0)

    def test_retry_on_exceptions_retries_with_callback(self):
        fn = Mock(side_effect=[RuntimeError("x"), "ok"])
        on_retry = Mock()

        result = retry_on_exceptions(
            fn,
            exceptions=(RuntimeError,),
            max_attempts=2,
            base_delay=0,
            max_delay=0,
            on_retry=on_retry,
            sleep=lambda *_: None,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        on_retry.assert_called_once()
