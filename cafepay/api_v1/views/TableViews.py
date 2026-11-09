import datetime
import json
import threading
import uuid

import requests
from asgiref.sync import async_to_sync
from django.core.validators import RegexValidator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django_filters import rest_framework as filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.generics import (ListAPIView, RetrieveAPIView,
                                     get_object_or_404, GenericAPIView, CreateAPIView)
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.consumers.DispatchConsumer import DispatchConsumer
from cafepay.api_v1.helpers import APIBadRequest, validate_table_operation, JOIN, TRANSFER, get_table_by_token, \
    notify_watchers, convert_jalali_to_gregorian, super_advanced_datetime_filter, AggregatedListAPIView, \
    get_payment_info, _desktop_notification_thread
from cafepay.api_v1.permissions import (CanCreateTable, CanManageTable, IsStaff, IsLoggedIn,
                                        CanUpdatePBR, IsLoggedInOrCanSeeCafeInfo)
from cafepay.api_v1.serializers.JoinSerializers import (JoinDetailedSerializer,
                                                        JoinSimpleSerializer, JoinSimpleParamsSerializer, )
from cafepay.api_v1.serializers.ProductSerializers import ProductPaymentInfoSerializer
from cafepay.api_v1.serializers.TableProductSerializers import (
    TableBulkProductSerializer, TableProductChangesSerializer)
from cafepay.api_v1.serializers.TableSerializers import TableCRUDSerializer, TableTokenRSerializer, \
    TableTokenCafeInfoSerializer, PublicTableTokenCafeInfoSerializer, \
    DummySerializer, ActivateTableTokenSerializer, TableTokenCSerializer
from cafepay.models import Cafe, Product, Table, TableToken, ScannedTable, ProductBillRelation, TableJoin, CafeWallet


class TableProductManageByToken(APIView):
    """
        add/remove product by table token

        POST to add product to table
        DELETE to remove product from table

        an active table token is required

        actions are done to the active bill of the table
    """

    permission_classes = (IsLoggedIn,)

    @staticmethod
    def post(request, *args, **kwargs):
        """
            Add product to table
        """
        with transaction.atomic():
            table = get_table_by_token(token=kwargs.get('table_token'),
                                       user_profile=request.user.user_profile)

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.add_product(product, request.user.user_profile)
            notify_watchers(table)
            return Response({})

    @staticmethod
    def delete(request, *args, **kwargs):
        with transaction.atomic():
            table = get_table_by_token(token=kwargs.get('table_token'),
                                       user_profile=request.user.user_profile)

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.remove_product(product, request.user.user_profile, False)
            notify_watchers(table)

            return Response(status=status.HTTP_204_NO_CONTENT)


def apply_table_product_changes(table, data, actor, staff=False):
    """Apply a complete order edit with one table lock and sorted product locks."""
    with transaction.atomic():
        table = Table.objects.select_for_update().get(pk=table.pk)
        if not staff and table.cafe.is_closed:
            raise APIBadRequest(_('Cafe Is Closed'), status_code=410)
        additions = data.get('add', [])
        removals = data.get('remove', [])
        product_ids = {item['product'].pk for item in additions + removals}
        list(Product.objects.select_for_update().filter(pk__in=product_ids).order_by('pk'))
        for action, items in (('remove', removals), ('add', additions)):
            for item in items:
                owner = item.get('user_profile', actor) if staff else actor
                is_staff = item.get('is_staff', True) if staff else False
                if action == 'add':
                    table.add_product(item['product'], owner, item['pickup_time'],
                                      is_staff=is_staff, quantity=item['count'])
                else:
                    table.remove_product(item['product'], owner, is_staff=is_staff,
                                         is_actor_staff=staff, quantity=item['count'])
        join = table.active_join
        if join is None:
            raise APIBadRequest(_('No active bill'))
        if 'description' in data:
            join.description = data['description']
            join.save(update_fields=['description'])
        transaction.on_commit(lambda: notify_watchers(table))
        return join


class TableProductChangesByToken(GenericAPIView):
    serializer_class = TableProductChangesSerializer
    permission_classes = (IsLoggedIn,)

    def get_table(self):
        token = self.kwargs['table_token']
        try:
            return get_table_by_token(token=token, user_profile=self.request.user.user_profile)
        except Http404:
            # Preorders use the opaque table UUID returned by the token endpoint.
            try:
                table_uuid = uuid.UUID(str(token))
            except (ValueError, TypeError, AttributeError):
                raise Http404()
            return get_object_or_404(Table, uuid=table_uuid, is_delete=False)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        join = apply_table_product_changes(
            self.get_table(), serializer.validated_data, request.user.user_profile)
        return Response(JoinSimpleSerializer(join, context=self.get_serializer_context()).data)


class TableProductChangesById(TableProductChangesByToken):
    permission_classes = (IsStaff,)

    def get_table(self):
        return get_object_or_404(Table, pk=self.kwargs['table_id'])

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        join = apply_table_product_changes(
            self.get_table(), serializer.validated_data, request.user.user_profile, staff=True)
        return Response(JoinSimpleSerializer(join, context=self.get_serializer_context()).data)


class TableBulkProductManageByToken(TableProductChangesByToken):
    serializer_class = TableBulkProductSerializer

    def post(self, request, *args, **kwargs):
        method = kwargs.get('method')
        if method not in ('post', 'delete'):
            return Response({'details': _('Invalid Method')}, status=400)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data['add' if method == 'post' else 'remove'] = data.pop('table_products')
        join = apply_table_product_changes(self.get_table(), data, request.user.user_profile)
        return Response(JoinSimpleSerializer(join, context=self.get_serializer_context()).data)


class TableBulkProductManageById(TableProductChangesById):
    serializer_class = TableBulkProductSerializer

    def post(self, request, *args, **kwargs):
        method = kwargs.get('method')
        if method not in ('post', 'delete'):
            return Response({'details': _('Invalid Method')}, status=400)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data['add' if method == 'post' else 'remove'] = data.pop('table_products')
        join = apply_table_product_changes(self.get_table(), data, request.user.user_profile, staff=True)
        return Response(JoinSimpleSerializer(join, context=self.get_serializer_context()).data)


class PBRUpdate(APIView):
    """
        Edit pbr on behalf of a user profile

        POST to add product to table
        DELETE to remove product from table

        required_permission: is_staff
    """

    permission_classes = (CanUpdatePBR,)

    def get_object(self):
        pbr = get_object_or_404(ProductBillRelation, pk=self.kwargs.get('pbr_id'))
        self.check_object_permissions(self.request, pbr)
        return pbr

    @staticmethod
    def validate_pbr(pbr):
        if pbr.bill.is_closed:
            raise APIBadRequest(_("Cannot modify closed bill"))

    def get_and_validate(self):
        pbr = self.get_object()
        self.validate_pbr(pbr)

        return pbr

    def post(self, request, *args, **kwargs):
        """
            Add product to pbr
        """

        pbr = self.get_and_validate()

        with transaction.atomic():
            table = pbr.bill.table
            product = pbr.product
            table.add_product(product, pbr.user_profile, pickup_time=pbr.pickup_time, is_staff=pbr.is_staff)

        notify_watchers(table)

        return Response({})

    def delete(self, request, *args, **kwargs):
        """
            remove product from pbr
        """

        pbr = self.get_and_validate()

        with transaction.atomic():
            table = pbr.bill.table
            product = pbr.product
            table.remove_product(product, pbr.user_profile, pbr.is_staff, True)

            return Response(status=status.HTTP_204_NO_CONTENT)


class TableProductManageByPk(APIView):
    """
        add/remove product by table pk as staff

        POST to add product to table
        DELETE to remove product from table

        actions are done to the active bill of the table

        required permission: is_staff
    """

    permission_classes = (IsStaff,)

    @staticmethod
    def post(request, *args, **kwargs):
        """
            Add product to table
        """
        with transaction.atomic():
            table = get_object_or_404(Table, pk=kwargs.get('table_id'))

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.add_product(product, request.user.user_profile, is_staff=True)
            notify_watchers(table)

            return Response({})

    @staticmethod
    def delete(request, *args, **kwargs):
        with transaction.atomic():
            table = get_object_or_404(Table, pk=kwargs.get('table_id'))

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.remove_product(product, request.user.user_profile, True)
            notify_watchers(table)

            return Response(status=status.HTTP_204_NO_CONTENT)


class TableSeparate(generics.UpdateAPIView):
    """
        Separate two tables

        required permissions = is_staff
    """

    lookup_field = 'pk'
    lookup_url_kwarg = 'table_id'

    queryset = Table.objects.all()
    serializer_class = DummySerializer

    permission_classes = (IsStaff,)

    def perform_update(self, serializer):
        instance = serializer.instance

        can_separate = False
        if instance.active_join:
            join = instance.get_or_create_join
            can_separate = len(join.bills.all()) > 1

        if can_separate:
            instance.separate()
        else:
            raise APIBadRequest(detail=_("Cannot separate singular table"))


class MakeTableJoin(generics.UpdateAPIView):
    """
        Join two tables

        required permission: is_staff
    """

    permission_classes = (IsStaff,)

    lookup_url_kwarg = 'table_id'
    lookup_field = 'pk'
    queryset = Table.objects.all()
    serializer_class = DummySerializer

    def perform_update(self, serializer):
        instance = serializer.instance
        table_y = get_object_or_404(Table, pk=self.kwargs.get('table_y'))

        validate_table_operation(instance, table_y, JOIN)

        serializer.instance.make_join(table_y)


class TableTransfer(generics.UpdateAPIView):
    """
        Transfer this table to table y

        if the current table's join is the same as the destination table join
        a separate on this table will be called instead

        required permission: is_staff
    """

    permission_classes = (IsStaff,)

    serializer_class = DummySerializer
    queryset = Table.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'table_id'

    def perform_update(self, serializer):
        instance = serializer.instance
        table_y = get_object_or_404(Table, pk=self.kwargs.get('table_y'))

        validate_table_operation(instance, table_y, TRANSFER)

        if instance.active_join == table_y.active_join:
            instance.separate()
        else:
            instance.transfer(table_y)


class TableSimpleBillView(RetrieveAPIView):
    """
        simple join info of the given table

        an active table token is required

        required permission: is_logged_in
    """
    permission_classes = (IsLoggedIn,)
    serializer_class = JoinSimpleSerializer

    def get_serializer_context(self):
        return {
            'request': self.request,
            'view': self,
            'has_my_payments': True
        }

    def get_object(self):
        table = get_object_or_404(TableToken,
                                  token=self.kwargs.get('table_token'),
                                  status=TableToken.ACTIVE).table
        active_join = table.active_join
        if not active_join:
            raise APIBadRequest(detail=_("No active join"), status_code=status.HTTP_204_NO_CONTENT)
        return active_join


class TableSimpleBillStaffView(RetrieveAPIView):
    """
        simple join info of the given table

        intended to get information about the join by
        table_id not by token which is for normal users

        required permission: is_staff
    """
    permission_classes = (IsStaff,)
    serializer_class = JoinSimpleSerializer

    def get_object(self):
        table = get_object_or_404(Table, pk=self.kwargs.get('table_id'))
        active_join = table.active_join
        if not active_join:
            raise APIBadRequest(detail=_("No active join"), status_code=status.HTTP_204_NO_CONTENT)
        return active_join


class TableDetailedBillView(RetrieveAPIView):
    """
        Detailed join info of the given table

        required permission: is_staff
    """
    permission_classes = (IsStaff,)
    serializer_class = JoinDetailedSerializer

    def get_object(self):
        table = get_object_or_404(Table, pk=self.kwargs.get('table_id'))
        return table.active_join


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


class TableStatusView(ListAPIView):
    """
        join simple view of all the tables of the cafe

        required permissions: is_staff
    """

    permission_classes = (IsStaff,)
    serializer_class = JoinSimpleSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return TableJoin.objects.filter(~Q(bills__bill_pbrs=None), bills__table__cafe=cafe).distinct().order_by(
            '-datetime')


class TableStatusFilterSet(filters.FilterSet):
    start_date = filters.CharFilter(label="start_date", required=True, validators=[
        RegexValidator(
            r'^[1][1-4][0-9]{2}\/((0[1-6]\/(0[1-9]|[1-2][0-9]|3[0-1]))|(0[7-9]\/(0[1-9]|[1-2][0-9]|30))|('
            r'1[0-1]\/(0[1-9]|[1-2][0-9]|30))|(12\/(0[1-9]|[1-2][0-9])))'),
    ])

    end_date = filters.CharFilter(label="end_date", required=True, validators=[
        RegexValidator(
            r'^[1][1-4][0-9]{2}\/((0[1-6]\/(0[1-9]|[1-2][0-9]|3[0-1]))|(0[7-9]\/(0[1-9]|[1-2][0-9]|30))|('
            r'1[0-1]\/(0[1-9]|[1-2][0-9]|30))|(12\/(0[1-9]|[1-2][0-9])))'),
    ])

    start_time = filters.TimeFilter(label="start_time", required=True)
    end_time = filters.TimeFilter(label="end_time", required=True)

    class Meta:
        model = TableJoin
        fields = ['start_date', ]

    def filter_queryset(self, queryset):
        fields = {}

        for key, value in self.form.cleaned_data.items():
            fields[key] = value

        start = convert_jalali_to_gregorian(date=fields.get('start_date').replace('/', '-'),
                                            _time=fields.get('start_time'))

        end = convert_jalali_to_gregorian(date=fields.get('end_date').replace('/', '-'),
                                          _time=fields.get('end_time'))

        start_time = start.time()
        start_date = start.date()
        end_time = (end + datetime.timedelta(seconds=59, microseconds=999999)).time()
        end_date = end.date()

        filtered_queryset = super_advanced_datetime_filter(queryset=queryset,
                                                           datetime_field="datetime",
                                                           start_date=start_date, start_time=start_time,
                                                           end_date=end_date, end_time=end_time)

        return filtered_queryset


class TableStatusFilteredView(AggregatedListAPIView):
    """
        join simple filtered view of all the tables of the cafe

        required permissions: is_staff

        all times and date must be in gregorian(persian format)
        ex: 1399-04-10
            yyyy-mm-dd

        sample response


            {
                "count": 23,
                "next": "api/v1/cafe/1/tables/join/simple/filtered/",
                "previous": null,
                "total_count": 427,         // total pbrs in the filtered result
                "total_amount": 4487880,
                "payed_amount": 4475380,
                "payed_amount_pos": 0,
                "payed_amount_cash": 4284380,
                "payed_amount_online": 191000,
                "refund_amount": 0,
                "net_payed_amount": 4475380,
                "net_amount": 12500
                "results": [
                    {
                        "pk": 127,
                        "sent": false,
                        "tables": [
                            {
                                "pk": 47,
                                "number": "میز تست"
                            }
                        ],
                        "join_number": 100,
                        "bill_products": [
                            {
                                "pk": 598,
                                "product": 690,
                                "count": 1,
                                "original_price": 6000,
                                "bill": {
                                    "pk": 127,
                                    "table": {
                                        "pk": 47,
                                        "number": "میز تست"
                                    }
                                },
                                "private_id": "ccc8ba88-adf0-4188-bb48-77169dd08242",
                                "discount": 0,
                                "is_staff": false,
                                "unit_amount": 6000,
                                "user_profile": {
                                    "pk": 1,
                                    "full_name": "علی پرویزی",
                                    "email": null,
                                    "first_name": "علی",
                                    "last_name": "پرویزی"
                                },
                                "my_payments": null,
                                "sent_to_kitchen": false,
                                "datetime": "2020-09-28T22:38:24.699146Z",
                                "invoices": [
                                    {
                                        "pk": 1050,
                                        "uuid": "9776ae2b-db76-4cc4-832a-e91123838661",
                                        "cafepay_fee": 0.0,
                                        "owner": "علی پرویزی",
                                        "create_datetime": "2020-10-24T11:56:24.677549Z",
                                        "last_payment_timestamp": null,
                                        "wallet": 2,
                                        "token": "",
                                        "transId": "",
                                        "card_number": "",
                                        "amount": 3500,
                                        "type": "1",
                                        "get_type_display": "Withdraw",
                                        "status": "4",
                                        "get_status_display": "Internal",
                                        "item": {
                                            "pk": 598,
                                            "name": "ماست موسیر رامک 250 گرم",
                                            "count": 1
                                        },
                                        "user_profile": {
                                            "pk": 1,
                                            "full_name": "علی پرویزی",
                                            "email": null,
                                            "first_name": "علی",
                                            "last_name": "پرویزی"
                                        },
                                        "tag": "1",
                                        "get_tag_display": "Payed for product",
                                        "method": "0",
                                        "get_method_display": "Online",
                                        "cafe": null
                                    },

                                ],
                                "product_data": {
                                    "pk": 690,
                                    "name": "ماست موسیر رامک 250 گرم",
                                    "order": 0
                                },
                                "payment_info": {
                                    "total_count": 1,
                                    "total_amount": 6000,
                                    "payed_amount": 6000,
                                    "payed_amount_pos": 0,
                                    "payed_amount_cash": 0,
                                    "payed_amount_online": 6000,
                                    "refund_amount": 0,
                                    "net_payed_amount": 6000,
                                    "net_amount": 0
                                }
                            }
                        ],
                        "force_close": false,
                        "cafe": {
                            "pk": 1,
                            "name": "کارخانه نواوری شیراز"
                        },
                        "is_closed": true,
                        "payment_info": {
                            "total_count": 1,
                            "total_amount": 6000,
                            "payed_amount": 6000,
                            "payed_amount_pos": 0,
                            "payed_amount_cash": 0,
                            "payed_amount_online": 6000,
                            "refund_amount": 0,
                            "net_payed_amount": 6000,
                            "net_amount": 0
                        },
                        "scanned": [
                            {
                                "user_profile": {
                                    "pk": 1,
                                    "username": "spsina",
                                    "full_name": "علی پرویزی",
                                    "private_id": "8485f7fc-0424-4310-9c4f-f8ef5eff100f"
                                },
                                "times": [
                                    "2020-09-28 22:35:28.244057+00:00",
                                ]
                            },
                        ],
                        "datetime": "2020-09-28T21:29:35.586243Z"
                    },
                 ],
            }

    """

    permission_classes = (IsStaff,)
    serializer_class = JoinSimpleSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.DjangoFilterBackend, ]
    filterset_class = TableStatusFilterSet

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return TableJoin.objects.filter(~Q(bills__bill_pbrs=None), bills__table__cafe=cafe).distinct().order_by(
            '-datetime')

    def get_aggregated_data(self, queryset):
        all_pbrs = ProductBillRelation.objects.filter(bill__join__in=queryset).distinct()

        return get_payment_info(all_pbrs)


class TableStatusFilterView(ListAPIView):
    """
        join simple view of all the tables of the cafe

        required permissions: is_staff
    """

    permission_classes = (IsStaff,)
    serializer_class = JoinSimpleSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return TableJoin.objects.filter(bills__table__cafe=cafe).distinct().order_by('-datetime')


class ProductPaymentInfoView(ListAPIView):
    """
        Products payment info

        required permissions: is_staff
    """

    permission_classes = (IsStaff,)
    serializer_class = ProductPaymentInfoSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return Product.objects.filter(cafe__pk=self.kwargs.get('cafe_id')).distinct()


class CafeTablesHumanReadable(APIView):
    permission_classes = (IsStaff,)

    def get(self, request, *args, **kwargs):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        tables = cafe.tables.order_by('id')
        joins = TableJoin.objects.filter(bills__table__cafe=cafe).distinct()

        all_join_data = JoinSimpleSerializer(instance=joins, many=True).data

        response = []
        from collections import OrderedDict

        for table in tables:
            active_join = None
            for join_data in all_join_data:
                if OrderedDict({'pk': table.pk, 'number': table.number}) in join_data.get('tables'):
                    active_join = join_data
                    break
            response += [{
                'pk': table.pk,
                'number': table.number,
                'active_join': active_join,
            }]

        return Response(response)


class TableCreateView(generics.CreateAPIView):
    """
        Table Create

        required permissions: can_create_table
    """
    permission_classes = (CanCreateTable,)
    queryset = Table.objects.all()
    serializer_class = TableCRUDSerializer

    def perform_create(self, serializer):
        table = serializer.save(cafe=get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')),
                                staff=self.request.user.user_profile)

        if table.table_type in [TableToken.PAYMENT_ONLY, TableToken.SELF_PICKUP]:
            table.uuid = uuid.uuid4()
            table.save()

        notify_watchers(table)


class TableRUDView(generics.RetrieveUpdateDestroyAPIView):
    """
        Table retrieve update delete

        required permission: can_manage_table

    """
    permission_classes = (CanManageTable,)
    queryset = Table.objects.all()
    serializer_class = TableCRUDSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'table_id'

    def perform_update(self, serializer):
        serializer.save(staff=self.request.user.user_profile)

    def perform_destroy(self, instance):
        instance.is_delete = True
        instance.staff = self.request.user.user_profile
        instance.save()


class TableListView(generics.ListAPIView):
    """
        List of cafe tables

        required permission: is_staff

    """
    permission_classes = (IsStaff,)
    serializer_class = TableCRUDSerializer

    def get_queryset(self):
        return get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')).tables.filter(is_delete=False)


class CafeAllTableTokens(ListAPIView):
    """
        List of all table tokens of the cafe

        any staff may see this
    """

    permission_classes = (IsStaff,)
    serializer_class = TableTokenRSerializer

    filter_backends = [DjangoFilterBackend, ]
    filter_fields = ['id', 'status', 'token', 'table']

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return TableToken.objects.filter(cafe=cafe)


class TableTokenCreateView(generics.CreateAPIView):
    """
        Create Table token
    """

    permission_classes = (IsStaff,)
    serializer_class = TableTokenCSerializer

    def perform_create(self, serializer):
        table = get_object_or_404(Table, pk=self.kwargs.get('table_id'))
        serializer.save(table=table, cafe=table.cafe)


class ActivateTableToken(generics.UpdateAPIView):
    """
        Activate a table token

        activate table token for a specific table

        all other table tokens are automatically deactivated.

        required permission: is_staff

    """

    permission_classes = (IsStaff,)

    lookup_url_kwarg = 'table_token'
    lookup_field = 'token'

    queryset = TableToken.objects.all()
    serializer_class = ActivateTableTokenSerializer

    def perform_update(self, serializer):
        other_tokens = serializer.instance.table.table_tokens.all()
        other_tokens.update(status=TableToken.INACTIVE)

        serializer.save(status=TableToken.ACTIVE)


class TableTokenCafeInfo(RetrieveAPIView):
    """
        Table and basic cafe info from table token

        all requests to this is endpoint are logged and restricted

    """
    permission_classes = (IsLoggedIn,)
    serializer_class = TableTokenCafeInfoSerializer

    def get_permissions(self):
        # Anonymous menu entry uses a separate, read-only response below.
        if not self.request.user.is_authenticated:
            return []
        return super().get_permissions()

    @staticmethod
    def create_token_table_pair(cafe, is_menu_only, table=None):
        _table_uuid = uuid.uuid4()
        if not table:
            table = Table.objects.create(cafe=cafe, number=_("Preorder"),
                                         uuid=_table_uuid, table_type=TableToken.SELF_PICKUP)

        _new_token = TableToken.objects.create(table=table, cafe=table.cafe, status=TableToken.ACTIVE,
                                               type=TableToken.SELF_PICKUP if not is_menu_only else TableToken.MENU_ONLY,
                                               token=uuid.uuid4()
                                               )

        return _new_token, table

    def get_object(self):
        try:
            token = TableToken.objects.get(token=self.kwargs.get('table_token'), status=TableToken.ACTIVE)
            _new_token = None

            # if token is self pick up, create a temp self pick up table first
            if token.type == TableToken.SELF_PICKUP:

                # check if the requested user has active preorder
                if self.request.user.is_authenticated:
                    active_preorder = self.request.user.user_profile.active_preorder
                else:
                    active_preorder = None

                # a cafe may have multiple self pickup tokens
                # if user is attempting to brows a cafe that he/she already has
                # preorders on, return the active preorder on that cafe
                # if user is not browsing  the same cafe, create a new table
                table = None
                if active_preorder:
                    table = get_object_or_404(Table, uuid=active_preorder)

                if table and table.cafe != token.cafe:
                    # discard the current order if no payments
                    active_join = table.active_join
                    if active_join.payment_info['net_payed_amount'] == 0:
                        # discard this join and create new table for the new cafe
                        active_join.force_close = True
                        active_join.save()
                        notify_watchers(table)

                        _new_token, _table = self.create_token_table_pair(cafe=token.cafe, is_menu_only=False)

                    else:
                        # there is payment
                        # generate a menu only token and table
                        _new_token, _table = self.create_token_table_pair(cafe=token.cafe, is_menu_only=True)
                elif table and table.cafe == token.cafe:
                    _new_token, _table = self.create_token_table_pair(cafe=token.cafe, is_menu_only=False, table=table)
                else:
                    _new_token, _table = self.create_token_table_pair(cafe=token.cafe, is_menu_only=False)
            if _new_token:
                return _new_token
            return token
        except TableToken.DoesNotExist:
            raise APIBadRequest(detail=_("Don't try this again"))

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            table_token = get_object_or_404(TableToken.objects.select_related('cafe'),
                token=self.kwargs.get('table_token'), status=TableToken.ACTIVE)
            if table_token.type not in (TableToken.MENU_ONLY, TableToken.SELF_PICKUP):
                self.permission_denied(request)
            # Do not allocate a preorder, log a scan, or evaluate the table's orders.
            return Response(PublicTableTokenCafeInfoSerializer(
                table_token, context=self.get_serializer_context()).data)
        table_token = self.get_object()

        # log the scan
        table = table_token.table
        active_bill = table.get_or_create_bill()

        if request.user.is_authenticated:
            ScannedTable.objects.create(user_profile=request.user.user_profile, bill=active_bill)

            # if the cafe has first time offers
            # and this is the first time this user is in this cafe
            # add the offer for the user
            if table.cafe.has_first_time_offer:
                # if this is the users first time in this cafe give him money :))))))
                if ScannedTable.objects.filter(user_profile=request.user.user_profile,
                                               bill__table__cafe=table.cafe).count() == 1:
                    cafe_wallet = CafeWallet.get_or_create(request.user.user_profile, table.cafe)
                    cafe_wallet.wallet.deposit(table.cafe.first_time_offer_amount,
                                               status=InvoiceConsts.PAYED,
                                               tag=InvoiceConsts.CHARGE_WALLET_FROM_CAFEPAY,
                                               method=InvoiceConsts.ONLINE)

            notify_watchers(table)

        serializer = self.get_serializer(table_token)
        return Response(serializer.data)
