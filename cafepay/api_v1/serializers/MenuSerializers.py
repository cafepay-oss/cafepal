from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers

from cafepay.api_v1.serializers.ProductSerializers import ProductImageCRSerializer
from cafepay.models import Menu, CharacterField, Product
from django.utils.translation import gettext as _


class ProductInfoSerializer(serializers.ModelSerializer):
    images = ProductImageCRSerializer(many=True, read_only=True)

    # for redoc to work properly:|
    price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['pk', 'name', 'description', 'original_price', 'order',
                  'remaining',
                  'is_delete', 'available', 'price', 'discount', 'images']

    @staticmethod
    def get_price(instance) -> int:
        return instance.price


class CategoryProductsSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CharacterField
        fields = ['pk', 'title', 'products',
                  'is_delete', 'menu',
                  'description', 'order']

    @swagger_serializer_method(serializer_or_field=ProductInfoSerializer)
    def get_products(self, category):
        if self.context.get('with_deleted'):
            products = category.products.all().order_by('order')
        else:
            products = category.products.filter(is_delete=False).order_by('order')

        return ProductInfoSerializer(instance=products, many=True).data


class CategoryBasedMenuSerializer(serializers.ModelSerializer):
    categories = CategoryProductsSerializer(many=True, source='not_deleted_categories')

    class Meta:
        model = Menu
        fields = ['pk', 'name', 'is_active', 'staff', 'categories']


class MenuCSerializer(serializers.ModelSerializer):
    class Meta:
        model = Menu
        fields = ['pk', 'name', 'staff', 'is_active', ]
        extra_kwargs = {'staff': {'read_only': True}, 'is_active': {'read_only': True}}


class MenuRUDSerializer(serializers.ModelSerializer):
    class Meta:
        model = Menu
        fields = ['pk', 'name', 'products', 'staff', 'is_active', ]
        extra_kwargs = {'staff': {'read_only': True}, 'is_active': {'read_only': True}}

    def validate_products(self, products):
        errors = []
        for product in products:
            if self.instance.cafe != product.cafe:
                errors += [{'%d' % product.pk: [_("Cafe mismatch"), ]}]

        if errors:
            raise serializers.ValidationError(errors)

        return products


class MenuAddRemoveProductSerializer(serializers.ModelSerializer):
    ADD = "ADD"
    REMOVE = "REMOVE"

    choices = (ADD,
               REMOVE)

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), write_only=True)
    action = serializers.ChoiceField(choices=choices, write_only=True)

    class Meta:
        model = Menu
        fields = ['pk', 'product', 'action', 'products']
        extra_kwargs = {
            'products': {'read_only': True}
        }

    def validate_product(self, product):
        if self.instance.cafe != product.cafe:
            raise serializers.ValidationError(_("Cafe mismatch"))
        return product


class MenuBulkAddRemoveProductSerializer(serializers.ModelSerializer):
    ADD = "ADD"
    REMOVE = "REMOVE"

    choices = (ADD,
               REMOVE)

    action = serializers.ChoiceField(choices=choices, write_only=True)

    class Meta:
        model = Menu
        fields = ['pk', 'action', 'products']

    def validate_products(self, products):
        errors = []
        for product in products:
            if self.instance.cafe != product.cafe:
                errors += [{'%d' % product.pk: [_("Cafe mismatch"), ]}]

        if errors:
            raise serializers.ValidationError(errors)

        return products


class ActivateMenuSerializer(serializers.ModelSerializer):
    class Meta:
        model = Menu
        fields = ['pk', ]


class MenuListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Menu
        fields = ['pk', 'name', 'staff', 'is_active', ]
