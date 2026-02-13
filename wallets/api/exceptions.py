from rest_framework import status
from rest_framework.views import exception_handler as drf_exception_handler

from wallets.api.responses import api_response


def _message_for_status(status_code):
    if status_code == status.HTTP_400_BAD_REQUEST:
        return ("Bad request.", "درخواست نامعتبر است.")
    if status_code == status.HTTP_404_NOT_FOUND:
        return ("Resource not found.", "منبع پیدا نشد.")
    if status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        return ("Method not allowed.", "متد مجاز نیست.")
    if status_code >= 500:
        return ("Internal server error.", "خطای داخلی سرور.")
    return ("Request failed.", "درخواست ناموفق بود.")


def _normalize_detail(payload):
    if isinstance(payload, dict) and set(payload.keys()) == {"detail"}:
        return payload["detail"]
    return payload


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is None:
        return api_response(
            detail=str(exc),
            message_en="Internal server error.",
            message_fa="خطای داخلی سرور.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            data=None,
        )

    message_en, message_fa = _message_for_status(response.status_code)
    return api_response(
        detail=_normalize_detail(response.data),
        message_en=message_en,
        message_fa=message_fa,
        status_code=response.status_code,
        data=None,
    )
