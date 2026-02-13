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

## Project Layout
- `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/wallet/`: Django project settings and URL wiring
- `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/wallets/models/`: `Wallet` and `Transaction` models
- `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/wallets/domain/`: business rules and services
- `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/wallets/integrations/`: HTTP client, retries, bank gateway, idempotency helpers
- `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/wallets/tasks/`: withdrawal executor
- `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/wallets/management/commands/`: executor command
- `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/wallets/tests/`: test suite

## Environment Configuration
The app loads `.env` automatically when the file exists in the project root.

1. Copy `/Users/amirwmr/apps/amir/Toman Interview Task/wallet/.env.sample` to `.env`.
2. Fill values for your environment.

### `.env` keys
- `DJANGO_SECRET_KEY`: required in production (`DEBUG=False`)
- `DEBUG`: `True` or `False`
- `ALLOWED_HOSTS`: comma-separated hosts
- `DATABASE_URL`: optional (`postgres://...` or `sqlite://...`)
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: used when `DATABASE_URL` is empty
- `BANK_BASE_URL`: bank mock base URL (default `http://127.0.0.1:8010`)
- `BANK_TIMEOUT`: bank request timeout in seconds (default `3`)
- `BANK_RETRY_COUNT`: retry attempts for timeout/connection failures (default `2`)
- `WITHDRAWAL_PROCESSING_STALE_SECONDS`: how long before reclaiming stale `PROCESSING` withdrawals (default `30`)
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
python3 manage.py migrate
python3 manage.py runserver 127.0.0.1:8000
```

Start the mock bank in another terminal:
```bash
cd /Users/amirwmr/apps/amir/Toman Interview Task/third-party
python3 app.py
```

## API
Base path: `/api/wallets/`

- `POST /api/wallets/{wallet_id}/deposit/`
- `POST /api/wallets/{wallet_id}/withdrawals/`
- `GET /api/wallets/{wallet_id}/`
- `GET /api/wallets/{wallet_id}/transactions/`
- `GET /health/`

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
python3 manage.py run_withdrawal_executor --limit 100
```

Run continuously:
```bash
python3 manage.py run_withdrawal_executor --loop --sleep-seconds 2 --limit 100
```

## Concurrency and Safety Design
- Money writes happen inside `transaction.atomic()` blocks.
- Due withdrawals are claimed with row locks; `skip_locked` is used when supported.
- Wallet rows are locked before debit/finalize operations.
- Debit uses `balance__gte` conditional update, so overdraft cannot happen.
- Failed bank calls mark transaction `FAILED` and refund the wallet.
- Each withdrawal has a unique `idempotency_key`; replays use the same key.
- Stale `PROCESSING` rows are reclaimed and retried safely to avoid stuck debits.

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
python3 -m isort manage.py wallet wallets
python3 -m black manage.py wallet wallets
python3 -m ruff check manage.py wallet wallets
python3 manage.py check
python3 manage.py test wallets.tests -v 2
```

## Scope Notes
- SQLite is default for local development.
- For stronger lock semantics under real multi-worker load, run with PostgreSQL.
