from rest_framework.response import Response


def api_response(*, detail, message_en, message_fa, status_code, data=None):
    return Response(
        {
            "detail": detail,
            "message": {
                "en": message_en,
                "fa": message_fa,
            },
            "status": status_code,
            "data": data,
        },
        status=status_code,
    )
