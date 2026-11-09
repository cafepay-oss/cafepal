from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import APIException

from cafepay.api_v1.consts import CharacterFieldConsts
from cafepay.api_v1.permissions import CanCreateListCategory, CanManageGroup, CanProductsBeViewed, IsStaff, \
    CanCreateListGroup
from cafepay.api_v1.serializers.CategorySerializers import CharFieldSerializer, \
    CharFieldListSerializer, CategoryAddRemoveSerializer, CategoryBulkAddRemoveSerializer, \
    CafeCategorySetOrderSerializer, GroupRUDSerializer, CategoryRUDSerializer
from cafepay.api_v1.serializers.MenuSerializers import CategoryProductsSerializer
from cafepay.models import Cafe, CharacterField
from django.utils.translation import gettext as _


class CategoryCreateView(generics.CreateAPIView):
    """
        Create category for shop

        required permissions: can_create_list_category
    """

    permission_classes = (CanCreateListCategory,)
    serializer_class = CharFieldSerializer

    def perform_create(self, serializer):
        serializer.save(cafe=get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')),
                        staff=self.request.user.user_profile,
                        type=CharacterFieldConsts.CATEGORY)


class GroupCreateView(generics.CreateAPIView):
    """
        Create Group for shop

        required permissions: can_create_list_group
    """

    permission_classes = (CanCreateListGroup,)
    serializer_class = CharFieldSerializer

    def perform_create(self, serializer):
        serializer.save(cafe=get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')),
                        staff=self.request.user.user_profile,
                        type=CharacterFieldConsts.GROUP)


class CategoryRUDView(generics.RetrieveUpdateDestroyAPIView):
    """
        Retrieve update delete category.

        this endpoint may be used to "set" products into this category

        set means, it does not add or remove the given list into this category
        it sets the given list as the products in this category.

        if this category is not emtpy, you cannot delete it

        required permissions: can_manage_category
    """
    permission_classes = (CanManageGroup,)
    serializer_class = CategoryRUDSerializer
    queryset = CharacterField.objects.filter(type=CharacterFieldConsts.CATEGORY)

    lookup_field = 'pk'
    lookup_url_kwarg = 'category_id'

    def perform_update(self, serializer):
        serializer.save(staff=self.request.user.user_profile)

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            api_protected_exception = APIException(detail=_("Only empty categories may be deleted"))
            api_protected_exception.status_code = status.HTTP_412_PRECONDITION_FAILED

            raise api_protected_exception


class SetIsDeleteToAllView(generics.DestroyAPIView):
    """
        delete category and all products in it.
        required permissions: can_manage_category
    """
    permission_classes = (CanManageGroup,)
    queryset = CharacterField.objects.filter(type=CharacterFieldConsts.CATEGORY)

    lookup_field = 'pk'
    lookup_url_kwarg = 'category_id'

    def perform_destroy(self, category):
        with transaction.atomic():
            category.products.update(is_delete=True)
            category.is_delete = True
            category.save()


class GroupRUDView(generics.RetrieveUpdateDestroyAPIView):
    """
        Retrieve update delete Group.

        this endpoint may be used to "set" products into this group

        set means, it does not add or remove the given list into this group
        it sets the given list as the products in this group.

        if this group is not emtpy, you cannot delete it

        required permissions: can_manage_group
    """
    permission_classes = (CanManageGroup,)
    serializer_class = GroupRUDSerializer
    queryset = CharacterField.objects.filter(type=CharacterFieldConsts.GROUP)

    lookup_field = 'pk'
    lookup_url_kwarg = 'group_id'

    def perform_update(self, serializer):
        serializer.save(staff=self.request.user.user_profile)

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            api_protected_exception = APIException(detail=_("Only empty groups may be deleted"))
            api_protected_exception.status_code = status.HTTP_412_PRECONDITION_FAILED

            raise api_protected_exception


class CategoryAddRemoveProductView(generics.RetrieveUpdateDestroyAPIView):
    """
        Category add/remove product

        required permissions: can_manage_category
    """
    permission_classes = (CanManageGroup,)
    serializer_class = CategoryAddRemoveSerializer
    queryset = CharacterField.objects.filter(type=CharacterFieldConsts.CATEGORY)

    lookup_field = 'pk'
    lookup_url_kwarg = 'category_id'

    def perform_update(self, serializer):
        if serializer.validated_data.get('action') == self.serializer_class.ADD:
            serializer.instance.products.add(serializer.validated_data.get('product'))
        else:
            serializer.instance.products.remove(serializer.validated_data.get('product'))


class CategoryBulkAddRemoveProductView(generics.RetrieveUpdateDestroyAPIView):
    """
        Category bulk add/remove product

        required permissions: can_manage_category
    """
    permission_classes = (CanManageGroup,)
    serializer_class = CategoryBulkAddRemoveSerializer
    queryset = CharacterField.objects.filter(type=CharacterFieldConsts.CATEGORY)

    lookup_field = 'pk'
    lookup_url_kwarg = 'category_id'

    def perform_update(self, serializer):
        if serializer.validated_data.get('action') == self.serializer_class.ADD:
            serializer.instance.products.add(*serializer.validated_data.get('products'))
        else:
            serializer.instance.products.remove(*serializer.validated_data.get('products'))


class CategoryProductsView(generics.RetrieveAPIView):
    """
        List of products in this category

        required_permissions: is_staff
    """
    permission_classes = (IsStaff,)

    serializer_class = CategoryProductsSerializer
    queryset = CharacterField.objects.filter(type=CharacterFieldConsts.CATEGORY)

    lookup_url_kwarg = 'category_id'
    lookup_field = 'pk'

    def get_serializer_context(self):
        return {
            'request': self.request,
            'with_deleted': True
        }


class CategoryListView(generics.ListAPIView):
    """
        Cafe Category List

        any one can see
    """
    serializer_class = CharFieldListSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id', None))
        return cafe.character_field.filter(type=CharacterFieldConsts.CATEGORY)


class GroupListView(generics.ListAPIView):
    """
        Cafe Group List

        any one can see
    """
    serializer_class = CharFieldListSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id', None))
        return cafe.character_field.filter(type=CharacterFieldConsts.GROUP)


class CategorySetOrderView(generics.RetrieveUpdateAPIView):
    """
    set cafe categories order
    sample request



         {
        "category_orders": [
            {
                "category": 11,
                "order": 1
            },
            {
                "category": 10,
                "order": 5
            }
        ]
        }



    """

    permission_classes = (IsStaff,)
    serializer_class = CafeCategorySetOrderSerializer
    queryset = Cafe.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_id'
