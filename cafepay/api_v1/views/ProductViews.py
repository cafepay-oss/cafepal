from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework import generics
from rest_framework.response import Response

from cafepay.api_v1.helpers import APIBadRequest
from cafepay.api_v1.permissions import CanManageProduct, CanCreateProduct, IsLoggedIn, CanProductsBeViewed, IsStaff
from cafepay.api_v1.serializers.ProductSerializers import ProductImageCRSerializer, ProductRSerializer, \
    ProductCommentSerializer, ProductImageUDSerializer, Toggle, ProductCUSerializer, CafeProductOrderSetSerializer, \
    ProductBulkUpdateSerializer
from cafepay.models import Product, Cafe, ProductImage, ProductRatingComment

from django_filters import rest_framework as filters
from rest_framework.filters import SearchFilter


class CreateProductImageView(generics.CreateAPIView):
    """
        Add Product Image.

        required permissions: can_manage_product
    """

    permission_classes = (CanManageProduct,)
    serializer_class = ProductImageCRSerializer

    def perform_create(self, serializer):
        serializer.save(product=get_object_or_404(Product, pk=self.kwargs.get('product_id')))


class ProductCreateView(generics.CreateAPIView):
    """
        Create a new product for the given cafe.

        required permission: can_create_product.
    """

    permission_classes = (CanCreateProduct,)
    serializer_class = ProductCUSerializer

    def perform_create(self, serializer):
        serializer.save(staff=self.request.user.user_profile,
                        cafe=get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')))


class MarkImageAsAvatar(generics.RetrieveUpdateAPIView):
    """
        Mark Product Image as avatar.

        input {pk of product}.

        mark the given image as an avatar for it's product.

        if any other image of this product is marked as not avatar.
    """

    permission_classes = (CanManageProduct,)
    serializer_class = ProductImageUDSerializer
    queryset = ProductImage.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'product_image_id'

    def update(self, request, *args, **kwargs):
        img = self.get_object()
        product = img.product

        product.images.all().update(is_avatar=False)
        img.is_avatar = True
        img.save()

        return Response({'details': _("Image marked as avatar")})


class ProductRateCommentAddView(generics.CreateAPIView):
    """
        add comment on product.

        any logged in user can add comment.

        comments will not show up until status set to accepted by admin.
    """
    permission_classes = (IsLoggedIn,)
    serializer_class = ProductCommentSerializer

    def perform_create(self, serializer):
        product = get_object_or_404(Product, pk=self.kwargs.get('product_id'))
        serializer.save(commenter=self.request.user.user_profile, product=product)


class ToggleAvailability(generics.UpdateAPIView):
    """
        Toggle Availability.

        Toggle Availability of a product.

        required permissions: can_manage_product
    """

    permission_classes = (CanManageProduct,)

    lookup_field = 'pk'
    lookup_url_kwarg = 'product_id'
    queryset = Product.objects.all()

    serializer_class = Toggle

    def put(self, request, *args, **kwargs):
        obj = self.get_object()
        obj.available = not obj.available
        obj.save()

        return Response(ProductRSerializer(instance=obj).data)


class ProductRateCommentListView(generics.ListAPIView):
    """
        List of accepted and valid comments and ratings of the product.

        anyone can see.
    """
    serializer_class = ProductCommentSerializer

    def get_queryset(self):
        product = get_object_or_404(Product, pk=self.kwargs.get('product_id'))
        return product.valid_comment_ratings


class UpdateProductImageView(generics.RetrieveUpdateDestroyAPIView):
    """
        update caption of product image.

        required permissions: can_manage_product
    """

    permission_classes = (CanManageProduct,)
    serializer_class = ProductImageUDSerializer
    queryset = ProductImage.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'product_image_id'


class ProductRUDView(generics.RetrieveUpdateDestroyAPIView):
    """
        Product RUD.

        Retrieve Product Info with GET method

        Delete Product with DELETE method

        Update Product with PUT method

        required permissions: can_manage_product
    """

    permission_classes = (CanManageProduct,)
    serializer_class = ProductCUSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'product_id'

    queryset = Product.objects.all()

    def perform_destroy(self, instance):
        product = instance
        staff = self.request.user.user_profile

        product.staff = staff
        product.is_delete = True

        product.save()


class ProductBulkUpdateView(generics.UpdateAPIView):
    permission_classes = (IsStaff,)

    serializer_class = ProductBulkUpdateSerializer
    product_update_serializer_class = ProductCUSerializer

    allowed_methods = ['PUT', ]

    def get_cafe(self):
        return get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))

    def validate_products(self):
        products_data = self.request.data.get('products', [])
        cafe = self.get_cafe()

        errors = []
        validated_products = []

        for product_data in products_data:
            pk = product_data.get('pk')
            try:
                validated_products.append(self.validate_product_data(cafe, pk, product_data))
            except Product.DoesNotExist:
                errors.append({'%d' % pk: _("Product with pk %d does not exist for the given cafe" % pk)})

        if errors:
            raise APIBadRequest({'details': errors})

        return validated_products

    def validate_product_data(self, cafe, pk, product_data):
        _product = Product.objects.get(pk=pk, cafe=cafe)
        product_serializer = self.product_update_serializer_class(instance=_product, data=product_data)
        product_serializer.is_valid(raise_exception=True)
        return product_serializer

    def update(self, request, *args, **kwargs) -> Response:
        validated_products = self.validate_products()
        products = self.update_products(validated_products)
        response_data = self.product_update_serializer_class(instance=products, many=True).data
        return Response({'products': response_data})

    @staticmethod
    def update_products(validated_products):
        products = []
        with transaction.atomic():
            for validated_product in validated_products:
                products.append((validated_product.save()))
        return products


class ProductListView(generics.ListAPIView):
    """
        List of all cafe products.

        required permissions: is_staff
    """

    permission_classes = (IsStaff,)
    serializer_class = ProductRSerializer

    def get_queryset(self):
        cafe = Cafe.objects.get(pk=self.kwargs.get('cafe_id', None))
        return cafe.products.all()


class CafeProductsList(generics.ListAPIView):
    serializer_class = ProductRSerializer
    filter_backends = [SearchFilter, ]
    search_fields = ['name', ]

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.products.all()


class CafeProductsSetOrderView(generics.RetrieveUpdateAPIView):
    """
    Set cafe products order

    sample request
    ```
    {
        "product_orders": [
        {
            "product": 683,
            "order": 1
        },
        {
            "product": 688,
            "order": 2
        }]
    }
    ```
    """

    permission_classes = (IsStaff,)
    serializer_class = CafeProductOrderSetSerializer
    queryset = Cafe.objects.all()

    lookup_url_kwarg = 'cafe_id'
    lookup_field = 'pk'
