from rest_framework import status as http_status
from rest_framework.views import APIView

from wallets.api.responses import api_response
from wallets.api.serializers import (
    DepositRequestSerializer,
    ScheduleWithdrawalRequestSerializer,
    TransactionFilterSerializer,
    TransactionSerializer,
    WalletSerializer,
)
from wallets.domain.exceptions import (
    IdempotencyConflict,
    InvalidAmount,
    InvalidExecuteAt,
    InvalidIdempotencyKey,
    WalletNotFound,
)
from wallets.domain.services import WalletService, WithdrawalService
from wallets.models import Transaction, Wallet


def get_wallet_or_none(wallet_id):
    return Wallet.objects.filter(pk=wallet_id).first()


class WalletDepositAPIView(APIView):
    def post(self, request, wallet_id):
        serializer = DepositRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(
                detail=serializer.errors,
                message_en="Invalid request body.",
                message_fa="درخواست نامعتبر است.",
                status_code=http_status.HTTP_400_BAD_REQUEST,
                data=None,
            )

        try:
            tx = WalletService.deposit(
                wallet_id=wallet_id,
                amount=serializer.validated_data["amount"],
            )
        except WalletNotFound:
            return api_response(
                detail=f"wallet={wallet_id} not found",
                message_en="Wallet was not found.",
                message_fa="کیف پول پیدا نشد.",
                status_code=http_status.HTTP_404_NOT_FOUND,
                data=None,
            )
        except InvalidAmount as exc:
            return api_response(
                detail=str(exc),
                message_en="Invalid amount.",
                message_fa="مبلغ نامعتبر است.",
                status_code=http_status.HTTP_400_BAD_REQUEST,
                data=None,
            )

        payload = {
            "wallet": WalletSerializer(tx.wallet).data,
            "transaction": TransactionSerializer(tx).data,
        }
        return api_response(
            detail="Deposit transaction created.",
            message_en="Deposit completed successfully.",
            message_fa="واریز با موفقیت انجام شد.",
            status_code=http_status.HTTP_201_CREATED,
            data=payload,
        )


class WalletWithdrawalScheduleAPIView(APIView):
    def post(self, request, wallet_id):
        serializer = ScheduleWithdrawalRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(
                detail=serializer.errors,
                message_en="Invalid request body.",
                message_fa="درخواست نامعتبر است.",
                status_code=http_status.HTTP_400_BAD_REQUEST,
                data=None,
            )

        body_idempotency_key = serializer.validated_data.get("idempotency_key")
        header_idempotency_key = request.headers.get("Idempotency-Key")
        if body_idempotency_key and header_idempotency_key:
            if body_idempotency_key != header_idempotency_key:
                return api_response(
                    detail="idempotency key mismatch between header and body",
                    message_en="Invalid withdrawal request.",
                    message_fa="درخواست برداشت نامعتبر است.",
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    data=None,
                )
        request_idempotency_key = header_idempotency_key or body_idempotency_key

        try:
            tx, created = WithdrawalService.schedule_withdrawal(
                wallet_id=wallet_id,
                amount=serializer.validated_data["amount"],
                execute_at=serializer.validated_data["execute_at"],
                idempotency_key=request_idempotency_key,
                include_created=True,
            )
        except WalletNotFound:
            return api_response(
                detail=f"wallet={wallet_id} not found",
                message_en="Wallet was not found.",
                message_fa="کیف پول پیدا نشد.",
                status_code=http_status.HTTP_404_NOT_FOUND,
                data=None,
            )
        except (InvalidAmount, InvalidExecuteAt, InvalidIdempotencyKey) as exc:
            return api_response(
                detail=str(exc),
                message_en="Invalid withdrawal request.",
                message_fa="درخواست برداشت نامعتبر است.",
                status_code=http_status.HTTP_400_BAD_REQUEST,
                data=None,
            )
        except IdempotencyConflict as exc:
            return api_response(
                detail=str(exc),
                message_en="Idempotency key already used for another request.",
                message_fa="کلید یکتایی برای درخواست دیگری استفاده شده است.",
                status_code=http_status.HTTP_409_CONFLICT,
                data=None,
            )

        payload = {
            "wallet": WalletSerializer(tx.wallet).data,
            "transaction": TransactionSerializer(tx).data,
        }
        if created:
            detail = "Withdrawal scheduled."
            message_en = "Withdrawal was scheduled successfully."
            message_fa = "برداشت با موفقیت زمان بندی شد."
            status_code = http_status.HTTP_201_CREATED
        else:
            detail = "Withdrawal request already exists for this idempotency key."
            message_en = "Withdrawal request already accepted."
            message_fa = "درخواست برداشت قبلا ثبت شده است."
            status_code = http_status.HTTP_200_OK

        return api_response(
            detail=detail,
            message_en=message_en,
            message_fa=message_fa,
            status_code=status_code,
            data=payload,
        )


class WalletDetailAPIView(APIView):
    def get(self, request, wallet_id):
        wallet = get_wallet_or_none(wallet_id)
        if wallet is None:
            return api_response(
                detail=f"wallet={wallet_id} not found",
                message_en="Wallet was not found.",
                message_fa="کیف پول پیدا نشد.",
                status_code=http_status.HTTP_404_NOT_FOUND,
                data=None,
            )

        recent_limit = 10
        recent_value = request.query_params.get("recent")
        if recent_value is not None:
            try:
                recent_limit = int(recent_value)
            except ValueError:
                return api_response(
                    detail="recent must be an integer",
                    message_en="Invalid query parameter.",
                    message_fa="پارامتر کوئری نامعتبر است.",
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    data=None,
                )

            if recent_limit < 1 or recent_limit > 100:
                return api_response(
                    detail="recent must be between 1 and 100",
                    message_en="Invalid query parameter.",
                    message_fa="پارامتر کوئری نامعتبر است.",
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    data=None,
                )

        transactions = wallet.transactions.order_by("-created_at")[:recent_limit]
        payload = {
            "wallet": WalletSerializer(wallet).data,
            "recent_transactions": TransactionSerializer(transactions, many=True).data,
        }
        return api_response(
            detail="Wallet details fetched.",
            message_en="Wallet details retrieved successfully.",
            message_fa="جزئیات کیف پول با موفقیت دریافت شد.",
            status_code=http_status.HTTP_200_OK,
            data=payload,
        )


class WalletTransactionsAPIView(APIView):
    def get(self, request, wallet_id):
        wallet = get_wallet_or_none(wallet_id)
        if wallet is None:
            return api_response(
                detail=f"wallet={wallet_id} not found",
                message_en="Wallet was not found.",
                message_fa="کیف پول پیدا نشد.",
                status_code=http_status.HTTP_404_NOT_FOUND,
                data=None,
            )

        filter_serializer = TransactionFilterSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return api_response(
                detail=filter_serializer.errors,
                message_en="Invalid query parameters.",
                message_fa="پارامترهای کوئری نامعتبر هستند.",
                status_code=http_status.HTTP_400_BAD_REQUEST,
                data=None,
            )

        filters = {}
        tx_type = filter_serializer.validated_data.get("type")
        tx_status = filter_serializer.validated_data.get("status")

        if tx_type:
            filters["type"] = tx_type
        if tx_status:
            filters["status"] = tx_status

        transactions = Transaction.objects.filter(
            wallet_id=wallet.id, **filters
        ).order_by("-created_at")

        payload = {
            "wallet": WalletSerializer(wallet).data,
            "count": transactions.count(),
            "results": TransactionSerializer(transactions, many=True).data,
        }
        return api_response(
            detail="Wallet transactions fetched.",
            message_en="Wallet transactions retrieved successfully.",
            message_fa="تراکنش های کیف پول با موفقیت دریافت شد.",
            status_code=http_status.HTTP_200_OK,
            data=payload,
        )
