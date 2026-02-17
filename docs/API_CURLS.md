# API Curl Guide

This document gives practical `curl` commands for all public API endpoints, with sample requests and expected responses.

Base URL used below:

```bash
BASE_URL="http://127.0.0.1:8000"
```

## 0) Create a Wallet (seed for testing)

There is no public "create wallet" endpoint right now.  
Create one from Django shell:

```bash
python manage.py shell -c "from wallets.models import Wallet; w=Wallet.objects.create(balance=100000); print(w.id, w.uuid, w.balance)"
```

Use the printed wallet id:

```bash
WALLET_ID=1
```

## 1) Health Check

### Request

```bash
curl -i "$BASE_URL/health/"
```

### Success Response (`200`)

```json
{"status":"ok"}
```

## 2) Deposit

Endpoint: `POST /api/wallets/{wallet_id}/deposit/`

### Request (without idempotency)

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/deposit/" \
  -H "Content-Type: application/json" \
  -d '{"amount": 2500}'
```

### Request (with idempotency header)

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/deposit/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: dep-001" \
  -d '{"amount": 2500}'
```

### Success Response (`201`) - first idempotent call or normal call

```json
{
  "detail": "Deposit transaction created.",
  "message": {
    "en": "Deposit completed successfully.",
    "fa": "واریز با موفقیت انجام شد."
  },
  "status": 201,
  "data": {
    "wallet": {
      "id": 1,
      "uuid": "8e5e607d-8d0f-44cb-9c8a-5c8de4b5f17b",
      "balance": 102500,
      "created_at": "2026-02-17T11:00:00Z",
      "updated_at": "2026-02-17T11:01:00Z"
    },
    "transaction": {
      "id": 10,
      "wallet_id": 1,
      "type": "DEPOSIT",
      "status": "SUCCEEDED",
      "amount": 2500,
      "execute_at": null,
      "idempotency_key": "dep-001",
      "external_reference": null,
      "bank_reference": null,
      "failure_reason": null,
      "created_at": "2026-02-17T11:01:00Z",
      "updated_at": "2026-02-17T11:01:00Z"
    }
  }
}
```

### Replay Response (`200`) - same idempotency key + same payload

```json
{
  "detail": "Deposit request already exists for this idempotency key.",
  "message": {
    "en": "Deposit request already accepted.",
    "fa": "درخواست واریز قبلا ثبت شده است."
  },
  "status": 200,
  "data": {
    "wallet": { "...": "..." },
    "transaction": { "...": "same transaction as first call" }
  }
}
```

### Validation Error (`400`) - bad body

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/deposit/" \
  -H "Content-Type: application/json" \
  -d '{"amount": "abc"}'
```

```json
{
  "detail": {
    "amount": ["A valid integer is required."]
  },
  "message": {
    "en": "Invalid request body.",
    "fa": "درخواست نامعتبر است."
  },
  "status": 400,
  "data": null
}
```

### Validation Error (`400`) - header/body idempotency mismatch

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/deposit/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: dep-header" \
  -d '{"amount": 2500, "idempotency_key": "dep-body"}'
```

```json
{
  "detail": "idempotency key mismatch between header and body",
  "message": {
    "en": "Invalid deposit request.",
    "fa": "درخواست واریز نامعتبر است."
  },
  "status": 400,
  "data": null
}
```

### Conflict (`409`) - same idempotency key + different payload

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/deposit/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: dep-002" \
  -d '{"amount": 1200}'

curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/deposit/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: dep-002" \
  -d '{"amount": 1300}'
```

```json
{
  "detail": "idempotency_key already used with a different deposit payload",
  "message": {
    "en": "Idempotency key already used for another request.",
    "fa": "کلید یکتایی برای درخواست دیگری استفاده شده است."
  },
  "status": 409,
  "data": null
}
```

### Not Found (`404`) - wallet does not exist

```bash
curl -i -X POST "$BASE_URL/api/wallets/999999/deposit/" \
  -H "Content-Type: application/json" \
  -d '{"amount": 2500}'
```

```json
{
  "detail": "wallet=999999 not found",
  "message": {
    "en": "Wallet was not found.",
    "fa": "کیف پول پیدا نشد."
  },
  "status": 404,
  "data": null
}
```

### Method Not Allowed (`405`)

```bash
curl -i "$BASE_URL/api/wallets/$WALLET_ID/deposit/"
```

## 3) Schedule Withdrawal

Endpoint: `POST /api/wallets/{wallet_id}/withdrawals/`

### Request (with idempotency header)

```bash
EXECUTE_AT=$(date -u -v+30M +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || python - <<'PY'
from datetime import datetime, timedelta, timezone
print((datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)

curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/withdrawals/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: wd-001" \
  -d "{\"amount\": 4000, \"execute_at\": \"$EXECUTE_AT\"}"
```

### Success Response (`201`) - first idempotent call or normal call

```json
{
  "detail": "Withdrawal scheduled.",
  "message": {
    "en": "Withdrawal was scheduled successfully.",
    "fa": "برداشت با موفقیت زمان بندی شد."
  },
  "status": 201,
  "data": {
    "wallet": {
      "id": 1,
      "uuid": "8e5e607d-8d0f-44cb-9c8a-5c8de4b5f17b",
      "balance": 102500,
      "created_at": "2026-02-17T11:00:00Z",
      "updated_at": "2026-02-17T11:01:00Z"
    },
    "transaction": {
      "id": 11,
      "wallet_id": 1,
      "type": "WITHDRAWAL",
      "status": "SCHEDULED",
      "amount": 4000,
      "execute_at": "2026-02-17T11:45:00Z",
      "idempotency_key": "wd-001",
      "external_reference": null,
      "bank_reference": null,
      "failure_reason": null,
      "created_at": "2026-02-17T11:15:00Z",
      "updated_at": "2026-02-17T11:15:00Z"
    }
  }
}
```

### Replay Response (`200`) - same idempotency key + same payload

```json
{
  "detail": "Withdrawal request already exists for this idempotency key.",
  "message": {
    "en": "Withdrawal request already accepted.",
    "fa": "درخواست برداشت قبلا ثبت شده است."
  },
  "status": 200,
  "data": {
    "wallet": { "...": "..." },
    "transaction": { "...": "same transaction as first call" }
  }
}
```

### Validation Error (`400`) - execute_at in past

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/withdrawals/" \
  -H "Content-Type: application/json" \
  -d '{"amount": 4000, "execute_at": "2020-01-01T00:00:00Z"}'
```

```json
{
  "detail": "execute_at must be in the future",
  "message": {
    "en": "Invalid withdrawal request.",
    "fa": "درخواست برداشت نامعتبر است."
  },
  "status": 400,
  "data": null
}
```

### Validation Error (`400`) - header/body idempotency mismatch

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/withdrawals/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: wd-header" \
  -d '{"amount": 4000, "execute_at": "2026-12-01T10:00:00Z", "idempotency_key": "wd-body"}'
```

### Conflict (`409`) - same idempotency key + different payload

```bash
curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/withdrawals/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: wd-002" \
  -d "{\"amount\": 3000, \"execute_at\": \"$EXECUTE_AT\"}"

curl -i -X POST "$BASE_URL/api/wallets/$WALLET_ID/withdrawals/" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: wd-002" \
  -d "{\"amount\": 3100, \"execute_at\": \"$EXECUTE_AT\"}"
```

### Not Found (`404`) - wallet does not exist

```bash
curl -i -X POST "$BASE_URL/api/wallets/999999/withdrawals/" \
  -H "Content-Type: application/json" \
  -d "{\"amount\": 4000, \"execute_at\": \"$EXECUTE_AT\"}"
```

## 4) Wallet Detail

Endpoint: `GET /api/wallets/{wallet_id}/`

### Request

```bash
curl -i "$BASE_URL/api/wallets/$WALLET_ID/"
```

### Request with recent limit

```bash
curl -i "$BASE_URL/api/wallets/$WALLET_ID/?recent=10"
```

### Success Response (`200`)

```json
{
  "detail": "Wallet details fetched.",
  "message": {
    "en": "Wallet details retrieved successfully.",
    "fa": "جزئیات کیف پول با موفقیت دریافت شد."
  },
  "status": 200,
  "data": {
    "wallet": {
      "id": 1,
      "uuid": "8e5e607d-8d0f-44cb-9c8a-5c8de4b5f17b",
      "balance": 102500,
      "created_at": "2026-02-17T11:00:00Z",
      "updated_at": "2026-02-17T11:10:00Z"
    },
    "recent_transactions": [
      {
        "id": 11,
        "wallet_id": 1,
        "type": "WITHDRAWAL",
        "status": "SCHEDULED",
        "amount": 4000,
        "execute_at": "2026-02-17T11:45:00Z",
        "idempotency_key": "wd-001",
        "external_reference": null,
        "bank_reference": null,
        "failure_reason": null,
        "created_at": "2026-02-17T11:15:00Z",
        "updated_at": "2026-02-17T11:15:00Z"
      }
    ]
  }
}
```

### Validation Error (`400`) - invalid `recent`

```bash
curl -i "$BASE_URL/api/wallets/$WALLET_ID/?recent=abc"
curl -i "$BASE_URL/api/wallets/$WALLET_ID/?recent=0"
curl -i "$BASE_URL/api/wallets/$WALLET_ID/?recent=101"
```

### Not Found (`404`)

```bash
curl -i "$BASE_URL/api/wallets/999999/"
```

## 5) Wallet Transactions

Endpoint: `GET /api/wallets/{wallet_id}/transactions/`

### Request (all)

```bash
curl -i "$BASE_URL/api/wallets/$WALLET_ID/transactions/"
```

### Request (filtered)

```bash
curl -i "$BASE_URL/api/wallets/$WALLET_ID/transactions/?type=DEPOSIT&status=SUCCEEDED"
curl -i "$BASE_URL/api/wallets/$WALLET_ID/transactions/?type=WITHDRAWAL&status=SCHEDULED"
```

Allowed values:
- `type`: `DEPOSIT`, `WITHDRAWAL`
- `status`: `SCHEDULED`, `PROCESSING`, `UNKNOWN`, `SUCCEEDED`, `FAILED`

### Success Response (`200`)

```json
{
  "detail": "Wallet transactions fetched.",
  "message": {
    "en": "Wallet transactions retrieved successfully.",
    "fa": "تراکنش های کیف پول با موفقیت دریافت شد."
  },
  "status": 200,
  "data": {
    "wallet": {
      "id": 1,
      "uuid": "8e5e607d-8d0f-44cb-9c8a-5c8de4b5f17b",
      "balance": 102500,
      "created_at": "2026-02-17T11:00:00Z",
      "updated_at": "2026-02-17T11:10:00Z"
    },
    "count": 2,
    "results": [
      {
        "id": 10,
        "wallet_id": 1,
        "type": "DEPOSIT",
        "status": "SUCCEEDED",
        "amount": 2500,
        "execute_at": null,
        "idempotency_key": "dep-001",
        "external_reference": null,
        "bank_reference": null,
        "failure_reason": null,
        "created_at": "2026-02-17T11:01:00Z",
        "updated_at": "2026-02-17T11:01:00Z"
      }
    ]
  }
}
```

### Validation Error (`400`) - invalid filter value

```bash
curl -i "$BASE_URL/api/wallets/$WALLET_ID/transactions/?type=INVALID"
curl -i "$BASE_URL/api/wallets/$WALLET_ID/transactions/?status=INVALID"
```

### Not Found (`404`)

```bash
curl -i "$BASE_URL/api/wallets/999999/transactions/"
```

## 6) Common API Error Envelope

All `/api/*` endpoints use this envelope:

```json
{
  "detail": "developer facing detail or validation object",
  "message": {
    "en": "English message",
    "fa": "پیام فارسی"
  },
  "status": 400,
  "data": null
}
```

Examples:
- `400` parse/validation/idempotency mismatch
- `404` wallet not found
- `405` wrong method
- `409` idempotency conflict
- `500` unexpected server error

Note: `/health/` is not under DRF error envelope and returns plain JSON.

