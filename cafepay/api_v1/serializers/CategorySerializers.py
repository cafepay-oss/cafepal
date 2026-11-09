from django.utils.translation import gettext as _
from rest_framework import serializers

from cafepay.api_v1.consts import CharacterFieldConsts
from cafepay.api_v1.serializers.ProductSerializers import ProductCategoryR
from cafepay.models import CharacterField, Product, Cafe


class CafeMenuScopeMixin:
    def validate(self, attrs):
        menu = attrs.get('menu')
        if menu:
            cafe_id = self.instance.cafe_id if self.instance else self.context['view'].kwargs['cafe_id']
            if menu.cafe_id != int(cafe_id):
                raise serializers.ValidationError({'menu': _('Cafe mismatch')})
        return attrs


class CharFieldSerializer(CafeMenuScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = CharacterField
        fields = ['pk', 'title',
                  'is_delete', 'menu',
                  'description', 'order']


class GroupRUDSerializer(CafeMenuScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = CharacterField
        fields = ['pk', 'title',
                  'is_delete', 'menu',
                  'group_products', 'staff', 'description', 'order']
        extra_kwargs = {
            'staff': {'read_only': True}
        }

    def validate_group_products(self, products):
        errors = []
        for product in products:
            if self.instance.cafe != product.cafe:
                errors += [{'%d' % product.pk: [_("Cafe mismatch")]}]

        if errors:
            raise serializers.ValidationError(errors)

        return products


class CategoryRUDSerializer(CafeMenuScopeMixin, serializers.ModelSerializer):
    class Meta:
        model = CharacterField
        fields = ['pk', 'title', 'products',
                  'is_delete', 'menu',
                  'staff', 'description', 'order']
        extra_kwargs = {
            'staff': {'read_only': True}
        }

    def validate_products(self, products):
        errors = []
        for product in products:
            if self.instance.cafe != product.cafe:
                errors += [{'%d' % product.pk: [_("Cafe mismatch")]}]

        if errors:
            raise serializers.ValidationError(errors)

        return products


class CharFieldListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CharacterField
        fields = ['pk', 'title', 'staff',
                  'is_delete', 'menu',
                  'description', 'order']


class CategoryAddRemoveSerializer(CafeMenuScopeMixin, serializers.ModelSerializer):
    ADD = "ADD"
    REMOVE = "REMOVE"

    choices = (ADD,
               REMOVE)

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), write_only=True)
    action = serializers.ChoiceField(choices=choices, write_only=True)

    class Meta:
        model = CharacterField
        fields = ['pk', 'product', 'action',
                  'is_delete', 'menu',
                  'products', 'description', 'order']
        extra_kwargs = {
            'products': {'read_only': True}
        }

    def validate_product(self, product):
        if self.instance.cafe != product.cafe:
            raise serializers.ValidationError(_("Cafe mismatch"))
        return product


class CategoryBulkAddRemoveSerializer(CafeMenuScopeMixin, serializers.ModelSerializer):
    ADD = "ADD"
    REMOVE = "REMOVE"

    choices = (ADD,
               REMOVE)

    action = serializers.ChoiceField(choices=choices, write_only=True)

    class Meta:
        model = CharacterField
        fields = ['pk', 'action', 'products', 'is_delete', 'menu']

    def validate_products(self, products):
        errors = []
        for product in products:
            if self.instance.cafe != product.cafe:
                errors += [{'%d' % product.pk: [_("Cafe mismatch")]}]

        if errors:
            raise serializers.ValidationError(errors)

        return products


class CategoryOrderSetSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=CharacterField.objects.all())
    order = serializers.IntegerField()


class CafeCategorySetOrderSerializer(serializers.ModelSerializer):
    category_orders = CategoryOrderSetSerializer(many=True, write_only=True)
    categories = CharFieldSerializer(many=True, read_only=True, source='categories_ordered')

    class Meta:
        model = Cafe
        fields = ['pk', 'category_orders', 'categories', 'payment_first', 'payment_only', 'has_delivery']

    def validate_category_orders(self, category_orders):

        for category_order in category_orders:
            if category_order.get('category').cafe != self.instance:
                raise serializers.ValidationError(_("Category %d cafe mismatch" % category_order.get('category').pk))

        return category_orders

    def update(self, instance, validated_data):

        for category_order in validated_data.get('category_orders'):
            category_order.get('category').order = category_order.get('order')
            category_order.get('category').save()

        return instance
