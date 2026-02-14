# Wallet Service

A Django + DRF wallet service with a transaction ledger, scheduled withdrawals, concurrency-safe execution, and a bank gateway integration.

## What It Does
- Creates and tracks wallet balances in integer minor units (`BigIntegerField`)
- Applies deposits immediately
- Schedules withdrawals for future execution (`execute_at`)
- Validates withdrawal balance at execution time (not schedule time)
- Executes due withdrawals safely under concurrent workers
- Calls a third-party bank service with retries and idempotency
- Keeps transaction lifecycle auditable: `SCHEDULED -> PROCESSING -> SUCCEEDED | FAILED`

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
- `BANK_RETRY_COUNT`: retry attempts for timeout/connection failures (default `2`)
- `WITHDRAWAL_PROCESSING_STALE_SECONDS`: how long before reclaiming stale `PROCESSING` withdrawals (default `30`)
- `EXECUTOR_LOCK_CONTENTION_MAX_RETRIES`: max consecutive lock-contention retries before executor exits (default `20`)
- `EXECUTOR_LOCK_CONTENTION_BACKOFF_SECONDS`: backoff sleep per contention retry (default `0.05`)
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

Withdrawal scheduling supports request idempotency:
- Send `Idempotency-Key` header (recommended) or `idempotency_key` in body.
- Same key + same payload returns the existing scheduled transaction (`200` replay).
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
- Stale `PROCESSING` rows are reclaimed and retried safely to avoid stuck debits.
- Lock contention is handled with bounded retry + backoff to reduce missed throughput under load.

## Bank Integration Behavior
- Request: `POST {BANK_BASE_URL}/`
- Timeout: `BANK_TIMEOUT`
- Retries: `BANK_RETRY_COUNT` for timeout/connection failures
- Response handling:
  - success only when HTTP 2xx and payload indicates success
  - `503` or payload failure -> transfer failure
  - network exception after retries -> transfer failure (`network_error`)

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
