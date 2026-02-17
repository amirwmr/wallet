# Wallet Service

A Django + DRF wallet service with a transaction ledger, scheduled withdrawals, concurrency-safe execution, and a bank gateway integration.

## What It Does
- Creates and tracks wallet balances in integer minor units (`BigIntegerField`)
- Applies deposits immediately
- Schedules withdrawals for future execution (`execute_at`)
- Validates withdrawal balance at execution time (not schedule time)
- Executes due withdrawals safely under concurrent workers
- Calls a third-party bank service with retries and idempotency
- Keeps transaction lifecycle auditable: `SCHEDULED -> PROCESSING -> SUCCEEDED | FAILED | UNKNOWN`

## Runtime and Tooling Versions
- Python: `>=3.10` (tested with `3.14.x`)
- Django: `5.2.1`
- Django REST Framework: `3.16.1`
- Tooling config (`pyproject.toml`) targets Python `3.10+`

## Project Layout
- `wallet/`: Django project settings and URL wiring
- `wallets/models/`: `Wallet` and `Transaction` models
- `wallets/domain/`: business rules and services
- `wallets/integrations/`: HTTP client, retries, bank gateway, idempotency helpers
- `wallets/tasks/`: withdrawal executor
- `wallets/management/commands/`: executor command
- `wallets/tests/`: test suite

## Environment Configuration
The app loads `.env` automatically when the file exists in the project root.

1. Copy `.env.sample` to `.env`.
2. Fill values for your environment.

### `.env` keys
- `DJANGO_SECRET_KEY`: required in production (`DEBUG=False`)
- `DEBUG`: `True` or `False`
- `ALLOWED_HOSTS`: comma-separated hosts
- `DATABASE_URL`: optional (`postgres://...` or `sqlite://...`)
- `DB_ENGINE`: defaults to `django.db.backends.sqlite3` when `DATABASE_URL` is empty
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: used when `DATABASE_URL` is empty
- `BANK_BASE_URL`: bank mock base URL (default `http://127.0.0.1:8010`)
- `BANK_TIMEOUT`: bank request timeout in seconds (default `3`)
- `BANK_RETRY_MAX_ATTEMPTS`: max transfer attempts including the first call (default `3`)
- `BANK_RETRY_BASE_DELAY`: exponential backoff base delay in seconds (default `0.2`)
- `BANK_RETRY_MAX_DELAY`: max backoff delay cap in seconds (default `3.0`)
- `BANK_MAX_RPS`: global bank request rate limit per second across workers (`0` disables)
- `BANK_RATE_LIMIT_REDIS_URL`: Redis URL used by distributed limiter
- `BANK_RATE_LIMIT_KEY`: Redis key used for limiter bucket state
- `BANK_REDIS_SOCKET_CONNECT_TIMEOUT`: Redis connect timeout in seconds (default `0.5`)
- `BANK_REDIS_SOCKET_TIMEOUT`: Redis read timeout in seconds (default `0.5`)
- `BANK_HTTP_MAX_CONNECTIONS`: number of HTTP host pools in requests adapter
- `BANK_HTTP_MAX_KEEPALIVE`: max keep-alive connections per host pool
- `BANK_STATUS_URL_TEMPLATE`: optional reconciliation status URL template
- `BANK_HONORS_IDEMPOTENCY`: if `False`, stale `PROCESSING` withdrawals are moved to `UNKNOWN` and queued for reconciliation instead of re-sending transfer (default `True`)
- `WITHDRAWAL_PROCESSING_STALE_SECONDS`: how long before reclaiming stale `PROCESSING` withdrawals (default `30`)
- `WITHDRAWAL_PROCESSING_TIMEOUT_SECONDS`: timeout for `PROCESSING` before reconciliation sweep (default `30`)
- `EXECUTOR_LOCK_CONTENTION_MAX_RETRIES`: max consecutive lock-contention retries before executor exits (default `20`)
- `EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS`: backoff sleep per contention retry (default `0.05`)
- `WORKER_LOOP_INTERVAL`: base delay between loop iterations (default `2.0`)
- `WORKER_STARTUP_JITTER_MAX`: random startup delay cap for worker desync (default `0.0`)
- `WORKER_LOOP_JITTER_MAX`: random jitter added to each loop sleep (default `0.5`)
- `WALLET_LOG_LEVEL`: log level for executor and bank gateway (default `INFO`)

Production guardrails in settings:
- `DJANGO_SECRET_KEY` must be set when `DEBUG=False`
- `ALLOWED_HOSTS` must not be empty when `DEBUG=False`
- `DATABASE_URL` or `DB_NAME` must be set when `DEBUG=False`

## Local Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python --version  # should be >= 3.10
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Start the mock bank in another terminal:
```bash
cd ../third-party
python3 app.py
```

## API
Base path: `/api/wallets/`

- `POST /api/wallets/{wallet_id}/deposit/`
- `POST /api/wallets/{wallet_id}/withdrawals/`
- `GET /api/wallets/{wallet_id}/`
- `GET /api/wallets/{wallet_id}/transactions/`
- `GET /health/`

Deposit and withdrawal scheduling support request idempotency:
- Send `Idempotency-Key` header (recommended) or `idempotency_key` in body.
- Same key + same payload returns the existing transaction (`200` replay).
- Same key + different payload returns `409`.

All API responses use a consistent envelope:
```json
{
  "detail": "developer-facing detail",
  "message": {
    "en": "English message",
    "fa": "پیام فارسی"
  },
  "status": 200,
  "data": {}
}
```

## Running the Withdrawal Executor
Run once:
```bash
python manage.py run_withdrawal_executor --limit 100
```

Run continuously:
```bash
python manage.py run_withdrawal_executor --loop --sleep-seconds 2 --limit 100
```

When lock contention happens under concurrent workers, the executor now retries with configurable backoff instead of exiting immediately.

## Concurrency and Safety Design
- Money writes happen inside `transaction.atomic()` blocks.
- Due withdrawals are claimed with row locks; `skip_locked` is used when supported.
- Wallet rows are locked before debit/finalize operations.
- Debit uses `balance__gte` conditional update, so overdraft cannot happen.
- Failed bank calls mark transaction `FAILED` and refund the wallet.
- Each withdrawal has a unique `idempotency_key`; replays use the same key.
- Stale `PROCESSING` rows are reclaimed and retried when bank idempotency is trusted (`BANK_HONORS_IDEMPOTENCY=True`).
- If bank idempotency is not trusted (`BANK_HONORS_IDEMPOTENCY=False`), stale `PROCESSING` rows are moved to `UNKNOWN` and queued for reconciliation without sending a second transfer request.
- Lock contention is handled with bounded retry + backoff to reduce missed throughput under load.

## Bank Integration Behavior
- Request: `POST {BANK_BASE_URL}/`
- Timeout: `BANK_TIMEOUT`
- Retries: `BANK_RETRY_MAX_ATTEMPTS` with exponential backoff + full jitter (`BANK_RETRY_BASE_DELAY`, `BANK_RETRY_MAX_DELAY`)
- Rate limiting: distributed Redis limiter controlled by `BANK_MAX_RPS`
- Response handling:
  - success only when HTTP 2xx and payload indicates success
  - non-2xx failures -> `FINAL_FAILURE` unless response is ambiguous
  - timeout/connection/ambiguous/5xx -> `UNKNOWN` (queued for reconciliation)

## Test and Quality Commands
```bash
python -m isort manage.py wallet wallets
python -m black manage.py wallet wallets
python -m ruff check manage.py wallet wallets
python manage.py check
python manage.py test wallets.tests -v 2
```

## Scope Notes
- SQLite is default for local development.
- For stronger lock semantics under real multi-worker load, run with PostgreSQL.
- Due-withdrawal fetch path uses a composite index on `(type, status, execute_at)` for better high-volume scanning.
