import calendar
import datetime

import jdatetime
import pytz
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _

from django.core.validators import RegexValidator
from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers

from cafepay.api_v1.serializers.AddressSerializers import UserProfileAddressDetailedSerializer
from cafepay.api_v1.serializers.BillSerializers import BillDetailedRetrieveSerializer, PBRRetrieveSerializer
from cafepay.api_v1.serializers.HelperSerializers import TimeParamsSerializer
from cafepay.api_v1.serializers.PBRPaymentSerializers import PBRPaymentSerializer
from cafepay.api_v1.serializers.WalletAndInvoiceSerializers import InvoiceSerializer
from cafepay.models import Bill, Product, TableJoin, ProductBillRelation, Table, Cafe, UserProfileAddress
from cafepay.api_v1.serializers.ShopSerializers import CafeBasicSerializer
from cafepay.api_v1.helpers import PaymentInfoField, get_table_simple_serializer, convert_jalali_to_gregorian, \
    get_cafe_info_serializer, get_product_basic_info_serializer


class TableJoinBaseSerializer(serializers.ModelSerializer):
    card_transfer = serializers.SerializerMethodField()

    def get_card_transfer(self, instance):
        transfer = instance.card_transfers.first()
        if not transfer:
            return None
        return {'uuid': str(transfer.uuid), 'status': transfer.status,
                'amount': transfer.amount, 'delivery_fee': transfer.delivery_fee}

    class Meta:
        model = TableJoin
        fields = ['pk', 'cafe', 'force_close', 'sent', 'card_transfer',
                  'last_changed_datetime', 'datetime',
                  'ready_time', 'description',
                  'include_delivery_fee',
                  'status', 'is_closed',
                  'is_self_pickup',
                  'address']


class JoinDetailedSerializer(TableJoinBaseSerializer):
    bills = BillDetailedRetrieveSerializer(many=True)
    cafe = CafeBasicSerializer(read_only=True)
    payment_info = PaymentInfoField(read_only=True)
    address = UserProfileAddressDetailedSerializer(read_only=True)

    class Meta(TableJoinBaseSerializer.Meta):
        fields = TableJoinBaseSerializer.Meta.fields + ['payment_info', 'scanned', 'bills']


class JoinSimpleParamsSerializer(TimeParamsSerializer):

    def validate(self, attrs):
        start_datetime = convert_jalali_to_gregorian(attrs.get('start_date'),
                                                     str(attrs.get('start_time')))
        end_datetime = convert_jalali_to_gregorian(attrs.get('end_date'),
                                                   str(attrs.get('end_time')))

        report_duration = end_datetime - start_datetime

        if report_duration > datetime.timedelta(days=45):
            raise serializers.ValidationError(_("Maximum report duration for daily report is 45 days"))

        return attrs


class JoinCancelSerializer(serializers.ModelSerializer):
    class Meta:
        model = TableJoin
        fields = ['pk', ]


class JoinSimpleSerializer(TableJoinBaseSerializer):
    bill_products = serializers.SerializerMethodField(read_only=True)
    tables = serializers.SerializerMethodField(read_only=True)

    payment_info = PaymentInfoField(read_only=True)
    join_number = serializers.SerializerMethodField()

    cafe = serializers.SerializerMethodField()
    address = UserProfileAddressDetailedSerializer(read_only=True)

    invoices = InvoiceSerializer(many=True)

    class Meta(TableJoinBaseSerializer.Meta):
        fields = TableJoinBaseSerializer.Meta.fields + ['tables', 'join_number', 'invoices',
                                                        'bill_products', 'payment_info', 'scanned', ]

    @staticmethod
    def get_cafe(table_join):
        serializer = get_cafe_info_serializer(simple=True)
        return serializer(instance=table_join.cafe).data

    @staticmethod
    def get_join_number(table_join):
        cafe = table_join.cafe
        now = timezone.now().date()

        count = cafe.joins.filter(datetime__date=now).count()
        return count + 100

    @staticmethod
    @swagger_serializer_method(serializer_or_field=get_table_simple_serializer()(many=True))
    def get_tables(instance) -> dict:
        tables = Table.objects.filter(bills__join=instance)
        return get_table_simple_serializer()(instance=tables, many=True).data

    @swagger_serializer_method(serializer_or_field=PBRRetrieveSerializer(many=True))
    def get_bill_products(self, instance):
        queryset = instance.all_products
        only_my_pbr = self.context.get('only_my_pbr', False)
        user_profile = None

        if (self.context.get('request', None) and
                self.context.get('request').user):
            user_profile = self.context.get('request').user.user_profile

        if user_profile and only_my_pbr:
            queryset = queryset.filter(Q(user_profile=user_profile) | Q(is_staff=True)).distinct()

        return PBRRetrieveSerializer(instance=queryset,
                                     context=self.context,
                                     many=True).data


class JoinAggregateSerializer(TableJoinBaseSerializer):
    tables = serializers.SerializerMethodField(read_only=True)
    address = UserProfileAddressDetailedSerializer(read_only=True)

    payment_info = PaymentInfoField(read_only=True)

    class Meta(TableJoinBaseSerializer.Meta):
        fields = TableJoinBaseSerializer.Meta.fields + ['tables', 'payment_info']

    @staticmethod
    @swagger_serializer_method(serializer_or_field=get_table_simple_serializer()(many=True))
    def get_tables(instance) -> dict:
        tables = Table.objects.filter(bills__join=instance)
        return get_table_simple_serializer()(instance=tables, many=True).data


class SendJoinSerializer(serializers.ModelSerializer):
    class Meta:
        model = TableJoin
        fields = ['pk', 'sent', 'force_close', 'is_closed']


class SetJoinReadyTimeSerializer(serializers.ModelSerializer):
    duration = serializers.DurationField(write_only=True)

    class Meta:
        model = TableJoin
        fields = ['pk', 'duration', 'ready_time']

        extra_kwargs = {
            'ready_time': {'read_only': True}
        }

    def update(self, table_join, validated_data):
        table_join.ready_time = timezone.now() + validated_data.get('duration')

        table_join.save()

        return table_join


class PbrSendToKitchenSerializer(serializers.ModelSerializer):
    sent_to_kitchen = serializers.BooleanField()

    class Meta:
        model = ProductBillRelation
        fields = ['pk', 'sent_to_kitchen']

    def update(self, productBillRelation, validated_data):
        if validated_data.get('sent_to_kitchen'):
            if productBillRelation.status < ProductBillRelation.KITCHEN:
                productBillRelation.status = ProductBillRelation.KITCHEN
                productBillRelation.save()

        return productBillRelation


class PBRAcceptSerializer(serializers.ModelSerializer):
    is_accepted = serializers.BooleanField()

    class Meta:
        model = ProductBillRelation
        fields = ['pk', 'is_accepted']

    def update(self, productBillRelation, validated_data):
        if validated_data.get('is_accepted'):
            if productBillRelation.status < ProductBillRelation.ACCEPTED:
                productBillRelation.status = ProductBillRelation.ACCEPTED
                productBillRelation.save()

        return productBillRelation


class PBRStatusSerializer(serializers.Serializer):
    pbr = serializers.PrimaryKeyRelatedField(queryset=ProductBillRelation.objects.all())
    status = serializers.ChoiceField(choices=ProductBillRelation.states)


class PBRMultiStatusSerializer(serializers.Serializer):
    pbrs = PBRStatusSerializer(many=True)

    def validate_pbrs(self, pbrs):
        errors = []

        # get cafe from view
        view = self.context.get('view')
        cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))

        for pbr_status in pbrs:
            if pbr_status.get('pbr').bill.table.cafe != cafe:
                errors.append({
                    'pbr': [
                        _("PBR with pk %d does not match the authorized cafe" % pbr_status.get('pbr').pk)
                    ]
                })

        if errors:
            raise serializers.ValidationError(errors)
        return pbrs

    def save(self, **kwargs):
        pbrs_status = self.validated_data.get('pbrs')

        tables_to_be_notified = set()

        for pbr_status in pbrs_status:
            pbr_status.get('pbr').status = pbr_status.get('status')
            pbr_status.get('pbr').save()
            tables_to_be_notified.add(pbr_status.get('pbr').bill.table)

        return tables_to_be_notified


class JoinDescriptionUpdate(serializers.ModelSerializer):
    """Update join description"""

    class Meta:
        model = TableJoin
        fields = ['pk', 'description']


class JoinSetIncludeDeliveryFeeSerializer(serializers.ModelSerializer):
    @transaction.atomic
    def update(self, table_join, validated_data):
        list(Table.objects.select_for_update().filter(
            pk__in=table_join.bills.values('table_id')).order_by('pk'))
        if table_join.card_transfers.filter(status__in=['submitted', 'confirmed', 'rejected']).exists():
            raise serializers.ValidationError('هزینه ارسال سفارش دارای رسید قابل تغییر نیست.')
        return super().update(table_join, validated_data)

    class Meta:
        model = TableJoin
        fields = ['pk', 'include_delivery_fee']


class JoinSetUserProfileAddressSerializer(serializers.ModelSerializer):
    user_profile_address = serializers.PrimaryKeyRelatedField(queryset=UserProfileAddress.objects.all(),
                                                              write_only=True, allow_null=True)

    class Meta:
        model = TableJoin
        fields = ['pk', 'user_profile_address', 'address', 'include_delivery_fee',
                  'is_self_pickup',
                  ]
        extra_kwargs = {'address': {'read_only': True}}

    def validate_user_profile_address(self, user_profile_address):
        if not user_profile_address:
            return None

        if self.context.get('request').user.is_authenticated:
            user_profile = self.context.get('request').user.user_profile

            if user_profile_address.is_clone or user_profile_address not in user_profile.addresses.all():
                raise serializers.ValidationError(_("Invalid User Profile Address"))
            return user_profile_address
        else:
            raise serializers.ValidationError(_("User must be logged in"))

    @transaction.atomic
    def update(self, table_join, validated_data):
        list(Table.objects.select_for_update().filter(
            pk__in=table_join.bills.values('table_id')).order_by('pk'))
        if table_join.card_transfers.filter(status__in=['submitted', 'confirmed', 'rejected']).exists():
            raise serializers.ValidationError('سفارش دارای رسید ثبت‌شده است و آدرس آن قابل تغییر نیست.')
        user_profile_address = validated_data.pop('user_profile_address', None)

        if not user_profile_address:
            table_join.address = None
            table_join.save()
        else:
            cloned_address = user_profile_address.clone()
            table_join.address = cloned_address
            table_join.save()

        _table_join = TableJoin.objects.filter(pk=table_join.pk)
        _table_join.update(**validated_data)

        table_join.refresh_from_db()

        return table_join
