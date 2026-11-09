from rest_framework import serializers
from cafepay.api_v1.helpers import get_user_profile_basic_info_serializer, get_cafe_info_serializer
from cafepay.models import Invoice, Wallet, ProductBillRelation, PBRRefund


class PBRRefundObjectSerializer(serializers.ModelSerializer):

    class Meta:
        model = PBRRefund
        fields = ['pk', 'pbr', 'invoice', 'amount']


class InvoiceSerializer(serializers.ModelSerializer):
    user_profile = get_user_profile_basic_info_serializer()(source='wallet.user_profile')
    cafe = get_cafe_info_serializer(True)(read_only=True, source='wallet.shop_wallet')
    item = serializers.SerializerMethodField()
    extra = serializers.SerializerMethodField()

    owner = serializers.CharField(read_only=True, source='wallet.owner_string')

    class Meta:
        model = Invoice
        fields = [
            'pk', 'uuid', 'cafepay_fee', 'owner',
            'create_datetime', 'last_payment_timestamp',
            'wallet', 'token', 'transId', 'card_number',
            'amount', 'type', 'get_type_display',
            'status', 'get_status_display', 'item',
            'extra',
            'user_profile', 'tag', 'get_tag_display',
            'method', 'get_method_display', 'cafe',
        ]

    @staticmethod
    def generic_serializer(instance):
        if type(instance) == ProductBillRelation:
            return {
                'pk': instance.pk,
                'name': instance.product.name,
                'count': instance.count
            }
        elif type(instance) == PBRRefund:
            return PBRRefundObjectSerializer(instance=instance).data
        return {
            'pk': 0,
            'name': 'N/A',
            'count': 0
        }

    def get_item(self, instance):
        return self.generic_serializer(instance.item)

    def get_extra(self, instance):
        return self.generic_serializer(instance.extra)


class InvoiceBasicSerializer(serializers.ModelSerializer):
    """Basic Invoice info serializer"""

    class Meta:
        model = Invoice
        fields = ['pk', 'amount', 'create_datetime', 'type', 'get_type_display',
                  'status', 'get_status_display',
                  'tag', 'get_tag_display', ]


class WalletSerializer(serializers.ModelSerializer):
    """Serialize wallet info and it's transactions"""
    invoice = InvoiceBasicSerializer(many=True, read_only=True)

    class Meta:
        model = Wallet
        fields = ['pk', 'balance', 'invoice']


class ChargeWalletInvoiceSerializer(serializers.ModelSerializer):
    """Create a charge wallet invoice"""
    amount = serializers.IntegerField(min_value=1)

    class Meta:
        model = Invoice
        fields = ['pk', 'amount', 'uuid']

        extra_kwargs = {
            'uuid': {'read_only': True}
        }


class PaymentInvoicesSerializer(serializers.Serializer):
    payed_invoices = InvoiceSerializer(read_only=True, many=True)
    refund_invoices = InvoiceSerializer(read_only=True, many=True)
