from django.db import transaction
from django.db.models import Q
from django.db.models.aggregates import Sum
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.permissions import ANY, has_perm_in_cafe, IsCustomer
from cafepay.api_v1.helpers import get_user_profile_basic_info_serializer, PaymentInfoField, clean_null_values, \
    get_product_basic_info_serializer
from cafepay.api_v1.serializers.WalletAndInvoiceSerializers import InvoiceSerializer
from cafepay.models import Bill, ProductBillRelation, Invoice, Table, Cafe
from django.utils.translation import gettext as _


class TableIDNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        fields = ['pk', 'number']


class BillTableSerializer(serializers.ModelSerializer):
    table = TableIDNameSerializer(read_only=True)

    class Meta:
        model = Bill
        fields = ['pk', 'table', ]


class MyPaymentInfoField(serializers.JSONField):
    class Meta:
        swagger_schema_fields = {
            "type": openapi.TYPE_OBJECT,
            "title": "My Payments Info field",
            "properties": {
                "payed_amount": openapi.Schema(
                    title="Payed Amount",
                    type=openapi.TYPE_INTEGER,
                ),
                "refund_amount": openapi.Schema(
                    title="Refund Amount",
                    type=openapi.TYPE_INTEGER,
                ),
                "net_amount": openapi.Schema(
                    title="Net Amount",
                    type=openapi.TYPE_INTEGER,
                ),
            },
        }


class PBRRetrieveSerializer(serializers.ModelSerializer):
    payment_info = PaymentInfoField(read_only=True)
    bill = BillTableSerializer(read_only=True)
    user_profile = get_user_profile_basic_info_serializer()(read_only=True)
    my_payments = serializers.SerializerMethodField(read_only=True)

    invoices = InvoiceSerializer(many=True, source='deposit_invoices')
    product_data = get_product_basic_info_serializer()(source='product')

    class Meta:
        model = ProductBillRelation
        fields = ['pk', 'product', 'count', 'original_price', 'bill', 'private_id',
                  'discount', 'is_staff', 'unit_amount', 'user_profile', 'my_payments',
                  'pickup_time', 'is_ready', 'is_delivered',
                  'status', 'get_status_display',
                  'preferred_payment_method',
                  'sent_to_kitchen', 'datetime', 'invoices', 'product_data', 'is_accepted',
                  'payment_info', ]

    def get_my_payments(self, instance):
        if self.context.get('has_my_payments'):
            user_profile = self.context.get('request').user.user_profile
            payed_invoices = Invoice.objects.filter(
                type=InvoiceConsts.WITHDRAW,
                wallet__user_profile=user_profile,
                pbr=instance,
                tag=InvoiceConsts.PAYED_FOR_PRODUCT,
            )

            refund_invoices = Invoice.objects.filter(
                type=InvoiceConsts.DEPOSIT,
                wallet__user_profile=user_profile,
                pbr=instance,
                tag=InvoiceConsts.REFUND,
            )

            payed_amount = payed_invoices.aggregate(payed_amount=Sum('amount'))

            refund_amount = refund_invoices.aggregate(refund_amount=Sum('amount'))

            clean_null_values(payed_amount)
            clean_null_values(refund_amount)

            net_amount = payed_amount['payed_amount'] - refund_amount['refund_amount']

            return {
                'payed_amount': payed_amount['payed_amount'],
                'refund_amount': refund_amount['refund_amount'],
                'net_amount': net_amount
            }

        else:
            return None


class PBRPaymentMethodUpdateSerializer(serializers.Serializer):
    pbr = serializers.PrimaryKeyRelatedField(queryset=ProductBillRelation.objects.all())
    preferred_payment_method = serializers.ChoiceField(choices=InvoiceConsts.methods)


class GroupPBRPaymentMethodSerializer(serializers.Serializer):
    """"
    update pbr payment methods
    return one of the pbrs after update
    """

    def update(self, instance, validated_data):
        raise NotImplemented

    def create(self, validated_data):
        with transaction.atomic():
            for item in validated_data['pbr_payment_methods']:
                pbr = item['pbr']
                pbr.preferred_payment_method = item['preferred_payment_method']
                pbr.save(update_fields=['preferred_payment_method'])
        return pbr

    pbr_payment_methods = PBRPaymentMethodUpdateSerializer(
        many=True, write_only=True, allow_empty=False)

    def validate_pbr_payment_methods(self, items):
        view = self.context['view']
        request = self.context['request']
        cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        staff = has_perm_in_cafe(request, cafe, ANY)
        seen = set()
        for item in items:
            pbr = item['pbr']
            if pbr.pk in seen:
                raise serializers.ValidationError(_('Duplicate payment item'))
            seen.add(pbr.pk)
            if pbr.bill.table.cafe_id != cafe.pk:
                raise serializers.ValidationError(_('PBR Cafe Mismatch'))
            if not staff:
                owner = pbr.bill.current_owner
                if (not owner or
                        not IsCustomer().has_object_permission(request, view, owner.join)):
                    raise serializers.ValidationError(_('You cannot change this order'))
        return items


class BillDetailedRetrieveSerializer(serializers.ModelSerializer):
    pre_bills = serializers.SerializerMethodField(
        read_only=True,
        help_text=_("Same structure"))
    product_bill_relations = serializers.SerializerMethodField(read_only=True)
    payment_info = PaymentInfoField(read_only=True)

    class Meta:
        model = Bill
        fields = ['pk', 'join', 'product_bill_relations', 'payment_info',
                  'payment_info', 'scanned', 'is_closed', 'pre_bills']

    @staticmethod
    @swagger_serializer_method(serializer_or_field=PBRRetrieveSerializer(many=True))
    def get_product_bill_relations(instance):
        return PBRRetrieveSerializer(instance=instance.all_products, many=True).data

    @staticmethod
    def get_pre_bills(instance):
        return BillDetailedRetrieveSerializer(
            instance=instance.pre_bill.all(),
            many=True).data


class BillSimpleRetrieveSerializer(serializers.ModelSerializer):
    product_bill_relations = serializers.SerializerMethodField(read_only=True)
    payment_info = PaymentInfoField(read_only=True)

    class Meta:
        model = Bill
        fields = ['pk', 'join', 'product_bill_relations', 'payment_info', 'is_closed', ]

    @staticmethod
    @swagger_serializer_method(serializer_or_field=PBRRetrieveSerializer(many=True))
    def get_product_bill_relations(instance):
        return PBRRetrieveSerializer(instance=instance.all_products, many=True).data
