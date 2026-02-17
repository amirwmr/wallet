from unittest.mock import Mock

import requests
from django.test import SimpleTestCase

from wallets.integrations.http import HttpClient, NetworkRequestFailed


class HttpClientTests(SimpleTestCase):
    def test_post_json_retries_on_network_errors_then_succeeds(self):
        session = Mock()
        response = Mock()
        response.status_code = 200

        session.post.side_effect = [
            requests.Timeout("first timeout"),
            requests.ConnectionError("network down"),
            response,
        ]

        client = HttpClient(
            session=session,
            connect_timeout=0.5,
            read_timeout=2.0,
            max_attempts=3,
            retry_base_delay=0,
            retry_max_delay=0,
        )

        result = client.post_json("http://bank.local/", json={"amount": 100})

        self.assertIs(result, response)
        self.assertEqual(session.post.call_count, 3)
        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["timeout"], (0.5, 2.0))

    def test_post_json_raises_after_retry_exhaustion(self):
        session = Mock()
        session.post.side_effect = requests.Timeout("always timeout")

        client = HttpClient(
            session=session,
            max_attempts=2,
            retry_base_delay=0,
            retry_max_delay=0,
        )

        with self.assertRaises(NetworkRequestFailed):
            client.post_json("http://bank.local/", json={"amount": 100})

        self.assertEqual(session.post.call_count, 2)
