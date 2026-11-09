from rest_framework import generics, status
from rest_framework.response import Response
from cafepay.models import CafeUserProfileRelation, Product
from cafepay.api_v1.permissions import CanCreateMenu, CanManageMenu, \
    CanProductsBeViewed, IsStaff
from cafepay.api_v1.serializers.MenuSerializers import (MenuRUDSerializer,
                                                        MenuListSerializer, CategoryBasedMenuSerializer,
                                                        ActivateMenuSerializer, MenuCSerializer,
                                                        MenuAddRemoveProductSerializer,
                                                        MenuBulkAddRemoveProductSerializer)

from cafepay.models import Cafe, Menu
from django.shortcuts import get_object_or_404


class MenuCreateView(generics.CreateAPIView):
    """
        Create new menu for the cafe.

        is staff and can create menu permission is required
    """

    permission_classes = (CanCreateMenu,)
    serializer_class = MenuCSerializer

    def perform_create(self, serializer):
        serializer.save(cafe=get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')),
                        staff=self.request.user.user_profile)


class MenuRetrieveUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    """
        Retrieve update delete a menu.

        Can be used to update menu products.
        this endpoint receives a list of products and updates the menu according to the list.
        do not use this api if want to remove or add some products.
        other methods and actions require CanManageMenu permission.
    """

    permission_classes = (CanManageMenu,)
    queryset = Menu.objects.all()
    serializer_class = MenuRUDSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'menu_id'

    def perform_update(self, serializer):
        serializer.save(staff=self.request.user.user_profile)


class MenuAddRemoveProductView(generics.UpdateAPIView):
    """
        menu add/remove product.

        required permission: can_manage_menu
    """

    permission_classes = (CanManageMenu,)
    queryset = Menu.objects.all()
    serializer_class = MenuAddRemoveProductSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'menu_id'

    def perform_update(self, serializer):
        if serializer.validated_data.get('action') == self.serializer_class.ADD:
            serializer.instance.products.add(serializer.validated_data.get('product'))
        else:
            serializer.instance.products.remove(serializer.validated_data.get('product'))


class MenuBulkAddRemoveProductView(generics.RetrieveUpdateAPIView):
    """
        menu bulk add/remove product.

        required permission: can_manage_menu
    """

    permission_classes = (CanManageMenu,)
    queryset = Menu.objects.all()
    serializer_class = MenuBulkAddRemoveProductSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'menu_id'

    def perform_update(self, serializer):
        if serializer.validated_data.get('action') == self.serializer_class.ADD:
            serializer.instance.products.add(*serializer.validated_data.get('products'))
        else:
            serializer.instance.products.remove(*serializer.validated_data.get('products'))


class MenuRemoveProductView(MenuAddRemoveProductView):

    def perform_update(self, serializer):
        serializer.instance.products.remove(serializer.validated_data.get('product'))


class ToggleMenuActivationStatus(generics.UpdateAPIView):
    """
        Toggle menu activation status.

        upon activating a menu all other menus will be deactivated automatically.

        required permissions: can_manage_menu
    """
    permission_classes = (CanManageMenu,)

    lookup_field = 'pk'
    lookup_url_kwarg = 'menu_id'

    serializer_class = ActivateMenuSerializer
    queryset = Menu.objects.all()

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_active:
            instance.is_active = False
        else:
            # deactivate all other menus
            instance.cafe.menus.all().update(is_active=False)

            # activate the current menu
            instance.is_active = True

        instance.save()

        return Response({'details': {'is_active': instance.is_active}})


class MenuListView(generics.ListAPIView):
    """
        List of menus of the cafe.

        if user is a staff all menus are returned.
        required permission: is_staff
    """

    permission_classes = (IsStaff,)
    serializer_class = MenuListSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.menus.all()


class CategoryProductMenuListView(generics.ListAPIView):
    """
        List of cafe menu, grouped by category.

        required permission: is_staff
    """
    permission_classes = (IsStaff, )
    serializer_class = CategoryBasedMenuSerializer

    def get_serializer_context(self):
        return {
            'request': self.request,
            'with_deleted': True
        }

    def get_queryset(self):
        return get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')).menus.all()


class CategoryProductMenuActiveView(generics.RetrieveAPIView):
    """
        Active cafe menu.

    """
    serializer_class = CategoryBasedMenuSerializer

    def get_object(self):
        return get_object_or_404(Menu,
                                 is_active=True,
                                 cafe__pk=self.kwargs.get('cafe_id'))
