from django.db.models.aggregates import Sum
from rest_framework.generics import get_object_or_404

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import clean_null_values, AggregatedListAPIView
from cafepay.api_v1.permissions import IsStaff
from cafepay.api_v1.serializers.WalletAndInvoiceSerializers import InvoiceSerializer
from cafepay.api_v1.views.ReportViews import StandardResultsSetPagination
from cafepay.models import Cafe, Invoice
from django_filters import rest_framework as filters


class InvoiceFilter(filters.FilterSet):
    class Meta:
        model = Invoice
        fields = {
            'method': ['exact', ],
            'type': ['exact', ],
            'status': ['exact', ],
            'amount': {'lt', 'gt', 'lte', 'gte'},
            'create_datetime': {'lt', 'gt', 'lte', 'gte'},
        }


class CafeWalletInvoiceListView(AggregatedListAPIView):
    """
    Cafe invoice

    sample response:
        {
        "count": 592,
        "next": "http://127.0.0.1:8000/api/v1/cafe/1/wallet/invoices/?page=2",
        "previous": null,

        "total_deposits": 7738920,
        "total_withdrawals": 0,
        "total_online_deposits": 437500,
        "total_pos_deposits": 0,
        "total_cash_deposits": 7301420,
        "total_cleared": 0,
        "total_uncleared": 437500

        "results": [
            {
                "pk": 364,
                "uuid": "7f79bac1-82a9-468c-95e7-8bb6e46d1b4f",
                "cafepay_fee": 0.0,
                "owner": "1-کارخانه نواوری شیراز",
                "create_datetime": "2020-10-24T11:56:24.677549Z",
                "last_payment_timestamp": null,
                "wallet": 1,
                "token": "",
                "transId": "",
                "card_number": "",
                "amount": 8000,
                "type": "0",
                "get_type_display": "Deposit",
                "status": "0",
                "get_status_display": "Payed",
                "item": {
                    "pk": 149,
                    "name": "نوشابه گاز دار لیموناد هوفنبرگ یک لیتر",
                    "count": 1
                },
                "user_profile": null,
                "tag": "1",
                "get_tag_display": "Payed for product",
                "method": "2",
                "get_method_display": "CASH",
                "cafe": {
                    "pk": 1,
                    "name": "کارخانه نواوری شیراز"
                }
            },
          ]
        }



    """

    permission_classes = (IsStaff,)
    serializer_class = InvoiceSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = (filters.DjangoFilterBackend,)

    filterset_class = InvoiceFilter

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        wallet = cafe.wallet
        return wallet.invoice.all().order_by('-create_datetime')

    def get_aggregated_data(self, queryset):
        total_deposits = queryset.filter(
            type=InvoiceConsts.DEPOSIT).aggregate(amount=Sum('amount')).get('amount')

        total_withdrawals = queryset.filter(
            type=InvoiceConsts.WITHDRAW).aggregate(amount=Sum('amount')).get('amount')

        total_online_deposits = queryset.filter(
            type=InvoiceConsts.DEPOSIT,
            method=InvoiceConsts.ONLINE).aggregate(amount=Sum('amount')).get('amount')

        total_pos_deposits = queryset.filter(
            type=InvoiceConsts.DEPOSIT,
            method=InvoiceConsts.POS).aggregate(amount=Sum('amount')).get('amount')
        total_cash_deposits = queryset.filter(
            type=InvoiceConsts.DEPOSIT,
            method=InvoiceConsts.CASH).aggregate(amount=Sum('amount')).get('amount')

        total_cleared = queryset.filter(
            type=InvoiceConsts.CLEARING).aggregate(amount=Sum('amount')).get('amount')

        aggregated_data = {
            'total_deposits': total_deposits,
            'total_withdrawals': total_withdrawals,
            'total_online_deposits': total_online_deposits,
            'total_pos_deposits': total_pos_deposits,
            'total_cash_deposits': total_cash_deposits,
            'total_cleared': total_cleared,
        }

        clean_null_values(aggregated_data)

        aggregated_data['total_uncleared'] = aggregated_data['total_online_deposits'] - aggregated_data['total_cleared']

        return aggregated_data

