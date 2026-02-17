import requests
from django.conf import settings

from wallets.integrations.retry import retry_on_exceptions


class NetworkRequestFailed(Exception):
    """Raised when network retries are exhausted."""


def build_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=settings.BANK_HTTP_MAX_CONNECTIONS,
        pool_maxsize=settings.BANK_HTTP_MAX_KEEPALIVE,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class HttpClient:
    def __init__(
        self,
        *,
        session=None,
        connect_timeout=1.0,
        read_timeout=3.0,
        max_attempts=1,
        retry_base_delay=0.0,
        retry_max_delay=0.0,
    ):
        self.session = session or build_session()
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_attempts = max_attempts
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay

    def post_json(self, url, *, json=None, headers=None):
        def send_once():
            return self.session.post(
                url,
                json=json,
                headers=headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )

        try:
            return retry_on_exceptions(
                send_once,
                exceptions=(requests.Timeout, requests.ConnectionError),
                max_attempts=self.max_attempts,
                base_delay=self.retry_base_delay,
                max_delay=self.retry_max_delay,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise NetworkRequestFailed("network request failed after retries") from exc

    def get_json(self, url, *, headers=None):
        def send_once():
            return self.session.get(
                url,
                headers=headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )

        try:
            return retry_on_exceptions(
                send_once,
                exceptions=(requests.Timeout, requests.ConnectionError),
                max_attempts=self.max_attempts,
                base_delay=self.retry_base_delay,
                max_delay=self.retry_max_delay,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise NetworkRequestFailed("network request failed after retries") from exc
