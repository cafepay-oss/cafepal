from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework.generics import CreateAPIView, RetrieveAPIView, ListAPIView, UpdateAPIView
from rest_framework.response import Response

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import APIBadRequest, notify_watchers
from cafepay.api_v1.permissions import IsLoggedIn, IsStaff
from cafepay.api_v1.serializers.BillSerializers import GroupPBRPaymentMethodSerializer
from cafepay.api_v1.serializers.PBRPaymentSerializers import PBRPaymentSessionCreateSerializer, \
    PBRPaymentManualSessionCreateSerializer, PBRRefundSerializer, PBRPaymentInvoicesSerializer, \
    PBRAmountInternalRefundSerializer, PBRInternalRefundSerializer, lock_refunds
from cafepay.api_v1.serializers.TableSerializers import DummySerializer
from cafepay.api_v1.serializers.WalletAndInvoiceSerializers import InvoiceSerializer
from cafepay.models import ProductBillRelation, Invoice, PBRRefund, TableJoin


class PBRPaymentSessionCreateView(CreateAPIView):
    """
        Create a new PBR payment session

        required permission: is_logged_in
    """

    permission_classes = (IsLoggedIn,)
    serializer_class = PBRPaymentSessionCreateSerializer

    def perform_create(self, serializer) -> None:
        serializer.save(user_profile=self.request.user.user_profile)

        # todo: check for notification


class PBRPaymentManualSessionCreateView(CreateAPIView):
    """
        Create a new manual PBR payment session

        ONLINE = '0'

        POS = '1'

        CASH = '2'

        required permission: is_logged_in
    """

    permission_classes = (IsStaff,)
    serializer_class = PBRPaymentManualSessionCreateSerializer

    def perform_create(self, serializer) -> None:
        _session = serializer.save(user_profile=self.request.user.user_profile)

        # all payments must have happened on the save table
        # so only on request is required
        payment = _session.payments.first()
        notify_watchers(payment.pbr.bill.table)


class PBRRefundView(CreateAPIView):
    """
        Refund

        required permission: is_staff
    """

    serializer_class = PBRRefundSerializer
    permission_classes = (IsStaff,)

    def perform_create(self, serializer) -> None:
        cafe_wallet = serializer.validated_data.get('cafe').wallet
        refunds = serializer.validated_data.get('refunds')

        with transaction.atomic():
            refunds = lock_refunds(refunds)
            for refund in refunds:

                # create refund item
                pbr_refund = PBRRefund.objects.create(pbr=refund.get('pbr'),
                                                      amount=refund.get('amount'),
                                                      invoice=refund.get('invoice'))

                r = cafe_wallet.transfer(amount=refund.get('amount'),
                                         to=refund.get('to').wallet,
                                         item=refund.get('pbr'),
                                         extra=pbr_refund,
                                         tag=InvoiceConsts.REFUND,
                                         status=InvoiceConsts.PAYED)
                if not r:
                    raise APIBadRequest(_("Transfer failed. Check your balance"))

        # refunds are on the same table so notify
        # table watchers by notifying the first refund table
        refund = refunds[0]
        notify_watchers(refund.get('pbr').bill.table)


class JoinRefundView(UpdateAPIView):
    serializer_class = DummySerializer
    queryset = TableJoin.objects.all()
    permission_classes = (IsStaff,)

    lookup_field = 'pk'
    lookup_url_kwarg = 'join_id'

    def put(self, request, *args, **kwargs):
        table_join = self.get_object()
        errors = table_join.refund_all_payed_invoices()

        if errors:
            return Response({
                'details': [
                    {'invoice': invoice.pk, 'amount': invoice.amount}
                    for invoice in errors]
            }, status=400)

        for bill in table_join.bills.all():
            notify_watchers(bill.table)

        return Response({'details': 'Refund Complete'})


class PBRInternalRefundView(CreateAPIView):
    """
        internal Refund

        required permission: is_staff
    """

    serializer_class = PBRInternalRefundSerializer
    permission_classes = (IsStaff,)

    def perform_create(self, serializer) -> None:
        cafe_wallet = serializer.validated_data.get('cafe').wallet
        refunds = serializer.validated_data.get('refunds')

        with transaction.atomic():
            refunds = lock_refunds(refunds)
            for refund in refunds:

                # create refund item
                pbr_refund = PBRRefund.objects.create(pbr=refund.get('pbr'),
                                                      amount=refund.get('amount'),
                                                      invoice=refund.get('invoice'))

                r = cafe_wallet.withdraw(amount=refund.get('amount'),
                                         item=refund.get('pbr'),
                                         extra=pbr_refund,
                                         tag=InvoiceConsts.REFUND,
                                         status=InvoiceConsts.PAYED)
                if not r:
                    raise APIBadRequest(_("Transfer failed. Check your balance"))

        # refunds are on the same table so notify
        # table watchers by notifying the first refund table
        refund = refunds[0]
        notify_watchers(refund.get('pbr').bill.table)


class PBRPaymentInvoicesView(RetrieveAPIView):
    """
        List of invoices of a categorized by payed/refund

        pbr private id required and user must be logged in
    """

    serializer_class = PBRPaymentInvoicesSerializer
    permission_classes = (IsLoggedIn,)
    queryset = ProductBillRelation.objects.all()

    lookup_field = 'private_id'
    lookup_url_kwarg = 'private_id'


class PBRInvoiceList(ListAPIView):
    """
        List of invoices of a PBR

        pbr private id required and user must be logged in
    """

    serializer_class = InvoiceSerializer
    permission_classes = (IsLoggedIn,)

    def get_queryset(self):
        pbr = get_object_or_404(ProductBillRelation, private_id=self.kwargs.get('private_id'))

        return Invoice.objects.filter(pbr=pbr)


class PBRPaymentMethodSetView(CreateAPIView):
    """

    set payment methods of pbrs

        # methods
        ONLINE = '0'
        POS = '1'
        CASH = '2'
        CARD_TO_CARD = '3'

    """

    permission_classes = (IsLoggedIn,)
    serializer_class = GroupPBRPaymentMethodSerializer

    def perform_create(self, serializer):
        pbr = serializer.save()
        notify_watchers(pbr.bill.table)
