from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers

from cafepay.api_v1.helpers import get_payment_info
from cafepay.models import Table, TableToken, TableJoin, ProductBillRelation, CafeWallet
from cafepay.api_v1.serializers.JoinSerializers import JoinSimpleSerializer
from cafepay.api_v1.serializers.ShopSerializers import CafeBasicSerializer
from django.utils.translation import gettext as _


class TableCRUDSerializer(serializers.ModelSerializer):
    is_preorder = serializers.BooleanField(default=False)

    class Meta:
        model = Table
        fields = ['pk', 'number', 'cafe', 'staff', 'is_preorder', 'table_type']
        read_only_fields = ('cafe', 'staff')

    def create(self, validated_data):
        is_preorder = validated_data.pop('is_preorder')
        _table = Table.objects.create(**validated_data)

        if is_preorder:
            _table.table_type = TableToken.SELF_PICKUP

        _table.save()

        return _table

    def update(self, instance, validated_data):
        is_preorder = validated_data.pop('is_preorder', None)
        if is_preorder is True:
            validated_data['table_type'] = TableToken.SELF_PICKUP
        elif is_preorder is False and instance.is_preorder:
            validated_data['table_type'] = TableToken.NORMAL
        return super().update(instance, validated_data)


class TableSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        fields = ['pk', 'number', 'uuid', 'table_type']


class TableTokenRSerializer(serializers.ModelSerializer):
    table = TableSimpleSerializer()

    class Meta:
        model = TableToken
        fields = ['pk', 'table', 'token', 'menu_only', 'type',
                  'get_type_display',
                  'has_delivery',
                  'status', 'get_status_display']


class TableTokenCSerializer(serializers.ModelSerializer):
    """Table token create serializer"""

    class Meta:
        model = TableToken
        fields = ['pk', 'table', 'token', 'menu_only',
                  'type', 'has_delivery',
                  'get_type_display',
                  'status', 'get_status_display']

        extra_kwargs = {
            'get_status_display': {"read_only": True},
            'status': {"read_only": True},
            'table': {"read_only": True}
        }


class PublicTableTokenCafeInfoSerializer(serializers.ModelSerializer):
    """Expose menu entry metadata without reading a table's customers or orders."""
    cafe = CafeBasicSerializer(read_only=True)

    class Meta:
        model = TableToken
        fields = ['token', 'cafe', 'type', 'has_delivery', 'get_type_display', 'menu_only']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.update({'pk': None, 'table': {'pk': None, 'uuid': None, 'number': ''},
                     'orders': None, 'has_staff_order': False, 'my_credit_in_cafe': 0})
        return data


class TableTokenCafeInfoSerializer(serializers.ModelSerializer):
    cafe = serializers.SerializerMethodField(read_only=True)
    table = TableSimpleSerializer()
    has_staff_order = serializers.SerializerMethodField()
    my_credit_in_cafe = serializers.SerializerMethodField()

    orders = JoinSimpleSerializer(source='table.active_join')

    class Meta:
        model = TableToken
        fields = ['pk', 'table', 'token', 'cafe',
                  'type',
                  'has_delivery',
                  'has_staff_order',
                  'my_credit_in_cafe',
                  'get_type_display',
                  'orders',
                  'menu_only']

    def get_my_credit_in_cafe(self, table_token):
        request = self.context.get('request')

        if request.user and request.user.is_authenticated:
            try:
                return CafeWallet.objects.get(user_profile=request.user.user_profile,
                                              cafe=table_token.table.cafe).wallet.balance
            except CafeWallet.DoesNotExist:
                return 0
        return 0

    @staticmethod
    def get_has_staff_order(table_token):
        table = table_token.table
        active_join = table.active_join

        if not active_join:
            return False

        return active_join.all_products.filter(is_staff=True).exists()

    # @swagger_serializer_method(serializer_or_field=JoinSimpleSerializer)
    # def get_orders(self, table_token):
    #     table = table_token.table
    #     active_join = table.active_join
    #     return JoinSimpleSerializer(instance=active_join, context=self.context)

    @swagger_serializer_method(serializer_or_field=CafeBasicSerializer)
    def get_cafe(self, instance) -> CafeBasicSerializer:
        cafe_info = CafeBasicSerializer(instance=instance.table.cafe).data
        return cafe_info


class TableJoinRetrieveSerializer(serializers.ModelSerializer):
    active_join = JoinSimpleSerializer(read_only=True)

    class Meta:
        model = Table
        fields = ['pk', 'number', 'active_join', 'table_type']


class ActivateTableTokenSerializer(serializers.ModelSerializer):

    class Meta:
        model = TableToken
        fields = ['pk', 'token', 'table', 'status',
                  'type', 'has_delivery',
                  'get_status_display', ]
        extra_kwargs = {
            'token': {'read_only': True},
            'status': {'read_only': True}
        }

    def validate_table(self, table):
        if table.cafe != self.instance.cafe:
            raise serializers.ValidationError(_("Cafe mismatch"))

        return table


class DummySerializer(serializers.Serializer):
    pass
