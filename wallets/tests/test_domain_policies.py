from datetime import datetime, timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from wallets.domain.exceptions import InvalidAmount, InvalidExecuteAt
from wallets.domain.policies import validate_future_execute_at, validate_positive_amount


class ValidatePositiveAmountTests(SimpleTestCase):
    def test_rejects_non_integer_values(self):
        for invalid in ("10", 10.5, True, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(InvalidAmount):
                    validate_positive_amount(invalid)

    def test_rejects_non_positive_integers(self):
        for invalid in (0, -1, -999):
            with self.subTest(invalid=invalid):
                with self.assertRaises(InvalidAmount):
                    validate_positive_amount(invalid)

    def test_accepts_positive_integer(self):
        self.assertEqual(validate_positive_amount(100), 100)


class ValidateFutureExecuteAtTests(SimpleTestCase):
    def test_rejects_non_datetime(self):
        with self.assertRaises(InvalidExecuteAt):
            validate_future_execute_at("2026-01-01T00:00:00Z")

    def test_rejects_naive_datetime(self):
        naive_dt = datetime.now() + timedelta(minutes=10)
        with self.assertRaises(InvalidExecuteAt):
            validate_future_execute_at(naive_dt)

    def test_rejects_non_future_datetime(self):
        now = timezone.now()
        with self.assertRaises(InvalidExecuteAt):
            validate_future_execute_at(now)

    def test_accepts_future_aware_datetime(self):
        execute_at = timezone.now() + timedelta(minutes=5)
        self.assertEqual(validate_future_execute_at(execute_at), execute_at)
