import requests

from wallets.integrations.retry import retry_on_exceptions


class NetworkRequestFailed(Exception):
    """Raised when network retries are exhausted."""


def build_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class HttpClient:
    def __init__(
        self, *, session=None, connect_timeout=1.0, read_timeout=3.0, max_retries=2
    ):
        self.session = session or build_session()
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries

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
                max_retries=self.max_retries,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise NetworkRequestFailed("network request failed after retries") from exc
