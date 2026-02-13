from django.urls import path

from wallets.api.views import (
    WalletDepositAPIView,
    WalletDetailAPIView,
    WalletTransactionsAPIView,
    WalletWithdrawalScheduleAPIView,
)

urlpatterns = [
    path(
        "<int:wallet_id>/deposit/",
        WalletDepositAPIView.as_view(),
        name="wallet-deposit",
    ),
    path(
        "<int:wallet_id>/withdrawals/",
        WalletWithdrawalScheduleAPIView.as_view(),
        name="wallet-withdrawals",
    ),
    path("<int:wallet_id>/", WalletDetailAPIView.as_view(), name="wallet-detail"),
    path(
        "<int:wallet_id>/transactions/",
        WalletTransactionsAPIView.as_view(),
        name="wallet-transactions",
    ),
]
