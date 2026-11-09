import math

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.generics import RetrieveAPIView, RetrieveUpdateAPIView, CreateAPIView

from cafepay.api_v1.helpers import notify_watchers, kavenegar_send_sms, datetime_to_local_str
from cafepay.api_v1.permissions import IsStaff, IsLoggedIn, IsCustomer, IsStaffOrCustomer
from cafepay.api_v1.serializers.JoinSerializers import JoinSimpleSerializer, JoinDetailedSerializer, SendJoinSerializer, \
    PbrSendToKitchenSerializer, PBRAcceptSerializer, PBRStatusSerializer, PBRMultiStatusSerializer, \
    SetJoinReadyTimeSerializer, JoinDescriptionUpdate, JoinCancelSerializer, JoinSetIncludeDeliveryFeeSerializer, \
    JoinSetUserProfileAddressSerializer
from cafepay.models import Bill, Product, Table, TableJoin, ProductBillRelation


class JoinSimpleRetrieveView(RetrieveAPIView):
    """
        Aggregated info of the given join

        required permission: is_staff
    """

    permission_classes = (IsStaffOrCustomer,)

    serializer_class = JoinSimpleSerializer
    queryset = TableJoin.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'join_id'


class JoinDetailedRetrieveView(RetrieveAPIView):
    """
        Detailed info of the given join

        required permissions: is_staff
    """

    permission_classes = (IsStaff,)

    serializer_class = JoinDetailedSerializer
    queryset = TableJoin.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'join_id'


class PbrSendToKitchen(RetrieveUpdateAPIView):
    """Send PBR to kitchen"""
    permission_classes = (IsStaff,)
    serializer_class = PbrSendToKitchenSerializer
    queryset = ProductBillRelation.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'pbr_id'

    def perform_update(self, serializer) -> None:
        pbr = serializer.save()
        notify_watchers(pbr.bill.table)


class PbrAcceptView(RetrieveUpdateAPIView):
    """accept PBR"""
    permission_classes = (IsStaff,)
    serializer_class = PBRAcceptSerializer
    queryset = ProductBillRelation.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'pbr_id'

    def perform_update(self, serializer) -> None:
        pbr = serializer.save()
        notify_watchers(pbr.bill.table)


class PBRStatusView(CreateAPIView):
    """
    Update PBR status


        PENDING = '0'
        ACCEPTED = '1'
        KITCHEN = '2'
        READY = '3'
        DELIVERED = '4'

    """
    permission_classes = (IsStaff,)
    serializer_class = PBRMultiStatusSerializer

    def perform_create(self, serializer):
        tables_to_be_notified = serializer.save()

        for table in tables_to_be_notified:
            notify_watchers(table)

            if table.is_preorder:
                if table.active_join.status in [ProductBillRelation.ACCEPTED,
                                                ProductBillRelation.READY]:
                    pbr = table.active_join.all_products.first()
                    if pbr:
                        user_profile = pbr.user_profile
                        template = "orderVerified" if (table.active_join.status ==
                                                       ProductBillRelation.ACCEPTED) else "orderReady"
                        tokens = {
                            'token': table.active_join.payment_info.get('total_amount'),
                            'token2': datetime_to_local_str(timezone.now()),
                        }

                        if template == "orderVerified":
                            if pbr.bill.join.ready_time:
                                tokens['token3'] = math.ceil((pbr.bill.join.ready_time -
                                                              timezone.now()).total_seconds() / 60)

                        kavenegar_send_sms(template, tokens, user_profile.phone_number)


class SendJoinView(RetrieveUpdateAPIView):
    """
        Update send status of a join

        required_permissions: is_staff
    """

    permission_classes = (IsStaff,)

    serializer_class = SendJoinSerializer
    queryset = TableJoin.objects.all()

    lookup_url_kwarg = 'join_id'
    lookup_field = 'pk'

    def perform_update(self, serializer) -> None:
        _object = serializer.save()

        for bill in _object.bills.all():
            notify_watchers(bill.table)


class SetJoinReadyView(RetrieveUpdateAPIView):
    """
        Update send ready time of a join

        required_permissions: is_staff
    """

    permission_classes = (IsStaff,)

    serializer_class = SetJoinReadyTimeSerializer
    queryset = TableJoin.objects.all()

    lookup_url_kwarg = 'join_id'
    lookup_field = 'pk'

    def perform_update(self, serializer) -> None:
        _object = serializer.save()

        for bill in _object.bills.all():
            notify_watchers(bill.table)


class CancelJoinView(RetrieveUpdateAPIView):
    """
    Invalidate a join by canceling all of it's pbrs
    just send put to this endpoint
    """
    permission_classes = (IsStaff,)
    serializer_class = JoinCancelSerializer
    lookup_field = "pk"
    lookup_url_kwarg = 'join_id'
    queryset = TableJoin.objects.all()

    def perform_update(self, serializer):
        with transaction.atomic():
            affected_tables = self.cancel_all_pbrs_and_force_close_join(serializer)
            transaction.on_commit(lambda: self.notify_affected_tables(affected_tables))

    def cancel_all_pbrs_and_force_close_join(self, serializer):
        affected_tables = self.cancel_all_pbrs(serializer.instance)
        self.force_close_join(serializer)
        return affected_tables

    @staticmethod
    def force_close_join(serializer):
        # A cancellation must not overwrite concurrently edited join metadata.
        TableJoin.objects.filter(pk=serializer.instance.pk).update(force_close=True)
        serializer.instance.force_close = True

    @staticmethod
    def notify_affected_tables(affected_tables):
        for table in affected_tables:
            notify_watchers(table)

    def cancel_all_pbrs(self, table_join):
        # Match ordinary order edits: tables, products, then PBRs, each by PK.
        # Include detached bills transferred into this join's current bills.
        table_ids = Bill.objects.filter(
            pk__in=Bill.related_bill_ids('join_id', table_join.pk)).values('table_id')
        tables = list(Table.objects.select_for_update().filter(pk__in=table_ids).order_by('pk'))
        products = TableJoin.objects.get(pk=table_join.pk).all_products
        product_ids = products.values('product_id')
        list(Product.objects.select_for_update().filter(pk__in=product_ids).order_by('pk'))
        for pbr in products.select_for_update().order_by('pk'):
            self._cancel_locked_pbr(pbr)
        return tables

    @staticmethod
    def _cancel_locked_pbr(pbr):
        if pbr.status == ProductBillRelation.CANCELED:
            return
        Product.objects.filter(pk=pbr.product_id).update(count=F('count') + pbr.count)
        pbr.status = ProductBillRelation.CANCELED
        pbr.save(update_fields=['status', 'datetime'])

    @staticmethod
    def cancel_pbr(pbr):
        # A caller may hold an instance read before another cancellation completed.
        with transaction.atomic():
            Table.objects.select_for_update().get(pk=pbr.bill.table_id)
            Product.objects.select_for_update().get(pk=pbr.product_id)
            current = ProductBillRelation.objects.select_for_update().get(pk=pbr.pk)
            CancelJoinView._cancel_locked_pbr(current)


class JoinUpdateDescriptionView(RetrieveUpdateAPIView):
    """Set join description"""

    permission_classes = [IsStaffOrCustomer, ]

    serializer_class = JoinDescriptionUpdate
    queryset = TableJoin.objects.all()

    lookup_url_kwarg = 'join_id'
    lookup_field = 'pk'

    def perform_update(self, serializer) -> None:
        join = serializer.save()

        if join.bills.first() and join.bills.first().table:
            notify_watchers(join.bills.first().table)


class JoinUpdateIncludeFeeView(RetrieveUpdateAPIView):
    """Set join include fee"""

    permission_classes = [IsStaffOrCustomer, ]

    serializer_class = JoinSetIncludeDeliveryFeeSerializer
    queryset = TableJoin.objects.all()

    lookup_url_kwarg = 'join_id'
    lookup_field = 'pk'

    def perform_update(self, serializer) -> None:
        join = serializer.save()

        if join.bills.first() and join.bills.first().table:
            notify_watchers(join.bills.first().table)


class JoinUpdateUserProfileAddressView(RetrieveUpdateAPIView):
    """Set join include fee"""

    permission_classes = [IsStaffOrCustomer, ]

    serializer_class = JoinSetUserProfileAddressSerializer
    queryset = TableJoin.objects.all()

    lookup_url_kwarg = 'join_id'
    lookup_field = 'pk'

    def perform_update(self, serializer) -> None:
        join = serializer.save()

        if join.bills.first() and join.bills.first().table:
            notify_watchers(join.bills.first().table)
