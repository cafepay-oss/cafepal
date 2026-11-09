from rest_framework import serializers
from django.utils.translation import gettext as _

from cafepay.api_v1.helpers import get_basic_menu_serializer, get_basic_char_field_serializer, \
    OverallRatingField, PaymentInfoField, get_product_basic_info_serializer
from cafepay.models import Product, ProductImage, ProductRatingComment, Cafe


class ProductCategoryR(serializers.ModelSerializer):
    """
        Used to serialize products inside a specific category and menu
    """

    group = get_basic_char_field_serializer()(read_only=True)

    class Meta:
        model = Product
        fields = ('pk', 'name', 'description', 'overall_rating', 'count',
                  'group', 'remaining',
                  'price', 'staff', 'is_delete')


class ProductImageCRSerializer(serializers.ModelSerializer):
    """
        Create Retrieve Image Of a product

    """

    class Meta:
        model = ProductImage
        fields = ['pk', 'image', 'caption', 'is_avatar']

        extra_kwargs = {
            'is_avatar': {'read_only': True}
        }


class ProductImageUDSerializer(serializers.ModelSerializer):
    """
        Update Delete image caption
    """

    class Meta:
        model = ProductImage
        fields = ['pk', 'caption', 'image']
        extra_kwargs = {
            'image': {'read_only': True}
        }


class ProductCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductRatingComment
        fields = ['pk', 'comment', 'rate', ]


class ProductRSerializer(serializers.ModelSerializer):
    menu = get_basic_menu_serializer()(many=True, read_only=True)
    category = get_basic_char_field_serializer()(read_only=True)
    group = get_basic_char_field_serializer()(read_only=True)
    images = ProductImageCRSerializer(many=True, read_only=True)

    # for redoc to work properly:|
    price = serializers.SerializerMethodField()
    overall_rating = OverallRatingField(read_only=True)

    class Meta:
        model = Product
        fields = ['pk', 'name', 'description', 'original_price', 'is_delete',
                  'group', 'remaining',
                  'available',
                  'price', 'discount', 'count', 'category', 'menu', 'images', 'overall_rating']

    @staticmethod
    def get_price(instance) -> int:
        return instance.price


class ProductPaymentInfoSerializer(serializers.ModelSerializer):
    # for redoc to work properly:|
    price = serializers.SerializerMethodField()

    payment_info = PaymentInfoField(read_only=True)

    class Meta:
        model = Product
        fields = ['pk', 'name', 'description', 'original_price', 'is_delete', 'available',
                  'payment_info', 'remaining',
                  'price', 'discount', 'count', ]

    @staticmethod
    def get_price(instance) -> int:
        return instance.price


class ProductCUSerializer(serializers.ModelSerializer):
    count = serializers.IntegerField(min_value=0, required=False)
    menu = get_basic_menu_serializer()(many=True, read_only=True)
    images = ProductImageCRSerializer(many=True, read_only=True)

    # for redoc to work properly:|
    price = serializers.SerializerMethodField()
    overall_rating = OverallRatingField(read_only=True)

    class Meta:
        model = Product
        fields = ['pk', 'name', 'count', 'order', 'description',
                  'group', 'remaining',
                  'original_price', 'is_delete', 'available',
                  'price', 'discount', 'category', 'menu', 'images', 'overall_rating']

    def validate(self, attrs):
        cafe_id = self.instance.cafe_id if self.instance else self.context['view'].kwargs['cafe_id']
        for name in ('category', 'group'):
            relation = attrs.get(name)
            if relation and relation.cafe_id != int(cafe_id):
                raise serializers.ValidationError({name: _('Cafe mismatch')})
        return attrs

    @staticmethod
    def get_price(instance) -> int:
        return instance.price


class ProductNestedUSerializer(ProductCUSerializer):
    class Meta(ProductCUSerializer.Meta):
        def __init__(self):
            _config = {'read_only': False, 'required': True}
            if not hasattr(self, 'extra_kwargs'):
                self.extra_kwargs = {'pk': _config}
            else:
                self.extra_kwargs['pk'] = _config


class ProductBulkUpdateSerializer(serializers.Serializer):
    products = ProductNestedUSerializer(many=True)


class ProductOrderSetSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    order = serializers.IntegerField()


class CafeProductOrderSetSerializer(serializers.ModelSerializer):
    product_orders = ProductOrderSetSerializer(many=True, write_only=True)

    products = get_product_basic_info_serializer()(many=True, source='products_ordered', read_only=True)

    class Meta:
        model = Cafe
        fields = ['pk', 'product_orders', 'products', 'payment_first', 'payment_only', 'has_delivery']

    def validate_product_orders(self, product_orders):
        for product_order in product_orders:
            if product_order.get('product').cafe != self.instance:
                raise serializers.ValidationError(_("Product %d cafe mismatch" % product_order.get('product').pk))

        return product_orders

    def update(self, instance, validated_data):
        product_orders = validated_data.get('product_orders')

        for product_order in product_orders:
            product_order.get('product').order = product_order.get('order')
            product_order.get('product').save()

        return instance


class ProductBasicRSerializer(serializers.ModelSerializer):
    images = ProductImageCRSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = ['pk', 'name', 'description', 'images', 'count', 'remaining']


class Toggle(serializers.Serializer):
    pass
