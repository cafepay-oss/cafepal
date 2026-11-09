from rest_framework import permissions
from django.shortcuts import get_object_or_404
from rest_framework.permissions import SAFE_METHODS

from cafepay.models import *
from django.utils.translation import gettext as _
from cafepay.api_v1.consts import CafeUserProfileRelationConsts

ANY = "__ANY__"


def is_authenticated(request):
    # check if is authenticated

    if not bool(request.user and request.user.is_authenticated):
        return False

    return True


def has_perm_in_cafe(request, cafe, permission):
    if not is_authenticated(request):
        return False

    if request.user.is_superuser:
        return True

    try:
        cupr = CafeUserProfileRelation.objects.filter(role__cafe=cafe,
                                                      user_profile=request.user.user_profile,
                                                      status=CafeUserProfileRelationConsts.VERIFIED).first()
        if not cupr:
            raise CafeUserProfileRelation.DoesNotExist

        user = cupr.user_profile.django_user

        if not permission == ANY:
            return user.has_perm("%s" % permission)
        return True

    except (CafeUserProfileRelation.DoesNotExist, UserProfile.DoesNotExist) as e:
        # logged in user is not a staff in this cafe
        return False


def get_free_is_auth_with_perm(request, cafe, permission):
    """
    No effect on GET method
    check for is staff status
    and permission specified
    :param request:
    :param cafe:
    :param permission:
    :return: True or False
    """

    if request.method == 'GET':
        return True

    return has_perm_in_cafe(request, cafe, permission)


class IsStaff(permissions.BasePermission):
    """
        Check if currently logged in user is a staff
        of the given cafe
    """

    def has_permission(self, request, view):
        if view.kwargs.get('table_id'):
            cafe = get_object_or_404(Table, pk=view.kwargs.get('table_id')).cafe
        elif view.kwargs.get('table_token'):
            cafe = get_object_or_404(TableToken, token=view.kwargs.get('table_token')).table.cafe
        elif view.kwargs.get('category_id'):
            cafe = get_object_or_404(CharacterField, pk=view.kwargs.get('category_id')).cafe
        elif view.kwargs.get('cafe_id'):
            cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        elif view.kwargs.get('bill_id'):
            cafe = get_object_or_404(Bill, pk=view.kwargs.get('bill_id')).table.cafe
        elif view.kwargs.get('pbr_id'):
            cafe = get_object_or_404(ProductBillRelation, pk=view.kwargs.get('pbr_id')).product.cafe
        elif view.kwargs.get('join_id'):
            cafe = get_object_or_404(TableJoin, pk=view.kwargs.get('join_id')).cafe
        elif view.kwargs.get('printer_id'):
            cafe = get_object_or_404(Printer, pk=view.kwargs.get('printer_id')).cafe
        elif view.kwargs.get('printer_job_id'):
            cafe = get_object_or_404(PrinterJob, pk=view.kwargs.get('printer_job_id')).printer.cafe
        elif view.kwargs.get('cafe_image_id'):
            cafe = get_object_or_404(Gallery, pk=view.kwargs.get('cafe_image_id')).cafe
        elif view.kwargs.get('region_price_id'):
            cafe = get_object_or_404(CafeRegionPrice, pk=view.kwargs.get('region_price_id')).cafe

        else:
            return False

        return has_perm_in_cafe(request, cafe, ANY)


class IsStaffOrCustomer(permissions.BasePermission):

    def has_permission(self, request, view):
        return is_authenticated(request) and hasattr(request.user, 'user_profile')

    def has_object_permission(self, request, view, obj) -> bool:
        return IsStaff().has_permission(request, view) or IsCustomer().has_object_permission(request, view, obj)


class CanUpdatePBR(permissions.BasePermission):
    """
        Check if currently logged in user is a staff
        of the given cafe
    """

    def has_permission(self, request, view):
        return is_authenticated(request) and hasattr(request.user, 'user_profile')

    def has_object_permission(self, request, view, obj) -> bool:
        cafe = get_object_or_404(ProductBillRelation, pk=view.kwargs.get('pbr_id')).product.cafe
        return has_perm_in_cafe(request, cafe, ANY)


class IsCustomer(permissions.BasePermission):
    """
        Check if currently logged in user is a customer on the given object
    """

    def has_object_permission(self, request, view, obj) -> bool:
        if not is_authenticated(request) or not hasattr(request.user, 'user_profile'):
            return False
        products = obj.all_products
        return products.filter(
            Q(user_profile=request.user.user_profile) |
            Q(invoices__wallet=request.user.user_profile.wallet)
        ).exists()


class IsLoggedIn(permissions.BasePermission):
    """

    """

    def has_permission(self, request, view):
        return is_authenticated(request) and hasattr(request.user, 'user_profile')


class IsElevatedUser(permissions.BasePermission):
    """
    Is superuser
    """

    def has_permission(self, request, view):
        if is_authenticated(request) and hasattr(request.user, 'user_profile'):
            return request.user.user_profile.is_elevated_user


class IsLoggedInOrCanSeeCafeInfo(permissions.BasePermission):
    """
    """

    def has_permission(self, request, view):
        table_token = get_object_or_404(TableToken, token=view.kwargs.get('table_token'))
        if table_token.menu_only:
            return True
        return is_authenticated(request)


class CanActivateTableToken(permissions.BasePermission):
    """
     Permission to activate table token
     any staff is allowed
    """

    def has_permission(self, request, view):
        table_token = get_object_or_404(TableToken, pk=view.kwargs.get('table_token_id'))
        cafe = table_token.table.cafe

        return has_perm_in_cafe(request, cafe, ANY)


class CanManagePost(permissions.BasePermission):
    """
        Permission to create | update | delete post
        No effect on get
    """

    message = _("You are not allowed to manage post")

    def has_permission(self, request, view):
        cafe = get_object_or_404(Post, pk=view.kwargs.get('post_id', None)).cafe
        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_manage_post')


class CanManageStaff(permissions.BasePermission):
    """
        Permission to add or remove staff
    """

    message = _("You must have can_manage_staff permission")

    def has_permission(self, request, view):
        obj = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        return has_perm_in_cafe(request, obj, 'cafepay.can_manage_staff')


class CanManageRole(permissions.BasePermission):
    """
        Permission to create update delete role
    """

    def has_permission(self, request, view):

        if view.kwargs.get('cafe_id'):
            cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        elif request.data.get('cafe_id'):
            cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        elif view.kwargs.get('role_id'):
            cafe = get_object_or_404(CafeUserProfileRelationRole, pk=view.kwargs.get('role_id')).cafe
        return has_perm_in_cafe(request, cafe, 'cafepay.can_manage_role')


class CanCreatePost(permissions.BasePermission):
    """
        Permission to create | update | delete post
        No effect on get
    """

    message = _("You are not allowed to manage post")

    def has_permission(self, request, view):
        cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_create_post')


class CanManageComment(permissions.BasePermission):
    """
        Who commented, can delete the comment
    """

    message = _("You are not allowed to manage this comment")

    def has_permission(self, request, view):
        if not is_authenticated(request):
            return False

        comment = get_object_or_404(Comment, pk=view.kwargs.get('comment_id'))
        return comment.user == request.user.user_profile


class CanManageProduct(permissions.BasePermission):
    """
        no effect on get method
        checks for authentication, is cafe staff and CanManageProduct permission
    """

    message = _("You are not allowed to manage this product")

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if view.kwargs.get('product_id'):
            cafe = get_object_or_404(Product, pk=view.kwargs['product_id']).cafe
        elif view.kwargs.get('product_image_id'):
            cafe = get_object_or_404(ProductImage, pk=view.kwargs['product_image_id']).product.cafe
        else:
            return False
        return has_perm_in_cafe(request, cafe, 'cafepay.can_manage_product')

    def has_object_permission(self, request, view, obj):

        if type(obj) == ProductImage:
            cafe = obj.product.cafe
        elif type(obj) == Product:
            cafe = obj.cafe

        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_manage_product')


class CanProductBeViewed(permissions.BasePermission):
    """
        check if cafe has permitted to show menu items or not
        if the requested user is a staff. permission is granted
    """

    message = _("You are not allowed to view this product")

    def has_permission(self, request, view):
        product = get_object_or_404(Product, pk=view.kwargs.get('product_id'))

        if product.cafe.menu_items_on:
            return True

        if not is_authenticated(request):
            return False

        # check staff status
        return has_perm_in_cafe(request, product.cafe, ANY)


class CanProductsBeViewed(permissions.BasePermission):
    """
        check if cafe has permitted to show menu items or not
        if the requested user is a staff. permission is granted
    """

    message = _("You are not allowed to view product list of this cafe")

    def has_permission(self, request, view):
        cafe_pk = view.kwargs.get('cafe_id')
        menu_pk = view.kwargs.get('menu_id')
        category_pk = view.kwargs.get('category_id')

        if cafe_pk is not None:
            """
                Products are either being requested from list cafe products endpoint
                or from retrieve menu endpoint
            """
            cafe = get_object_or_404(Cafe, pk=cafe_pk)
        elif menu_pk is not None:
            cafe = get_object_or_404(Menu, pk=menu_pk).cafe
        elif category_pk is not None:
            cafe = get_object_or_404(CharacterField, pk=category_pk).cafe

        if cafe.menu_items_on:
            return True

        if not is_authenticated(request):
            return False

        return has_perm_in_cafe(request, cafe, ANY)


class CanCreateProduct(permissions.BasePermission):
    """
        no effect on get method
        check for staff status and permission for product creation
    """

    message = _("You are not allowed to create products for this cafe")

    def has_permission(self, request, view):
        cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_create_product')


class CanCreateMenu(permissions.BasePermission):
    """
        no effect on GET request
        check for staff status and can create menu permission
    """

    message = _("You are not allowed to create menus for this cafe")

    def has_permission(self, request, view):
        cafe = Cafe.objects.get(pk=view.kwargs.get('cafe_id'))
        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_create_menu')


class CanManageMenu(permissions.BasePermission):
    """
        no effect on GET method
        is staff and can manage menu required
    """

    def has_object_permission(self, request, view, obj):
        return get_free_is_auth_with_perm(request, obj.cafe, 'cafepay.can_manage_menu')


class CanCreateListCategory(permissions.BasePermission):
    """
        No effect on GET method
        staff users with can_create_list_category are granted permission
    """

    def has_permission(self, request, view):
        cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        return get_free_is_auth_with_perm(request, cafe, "cafepay.can_create_list_category")


class CanCreateListGroup(permissions.BasePermission):
    """
        No effect on GET method
        staff users with can_create_list_group are granted permission
    """

    def has_permission(self, request, view):
        cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        return get_free_is_auth_with_perm(request, cafe, "cafepay.can_create_list_group")


class CanManageCategory(permissions.BasePermission):
    """
        No effect on GET method
        staff users with can_manage_category are granted permission
    """

    def has_object_permission(self, request, view, obj):
        cafe = obj.cafe
        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_manage_category')


class CanManageGroup(permissions.BasePermission):
    """
        No effect on GET method
        staff users with can_manage_group are granted permission
    """

    def has_object_permission(self, request, view, obj):
        cafe = obj.cafe
        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_manage_group')


class CanUpdateCafe(permissions.BasePermission):
    """
        no effect on GET
        can update cafe permission required
    """

    def has_object_permission(self, request, view, obj):
        return has_perm_in_cafe(request, obj, 'cafepay.can_manage_cafe')


class CanCreateTable(permissions.BasePermission):
    """
        can create table
    """

    def has_permission(self, request, view):
        cafe = get_object_or_404(Cafe, pk=view.kwargs.get('cafe_id'))
        return has_perm_in_cafe(request, cafe, 'cafepay.can_create_table')


class CanManageTable(permissions.BasePermission):
    """
        no effect on GET request
    """

    def has_object_permission(self, request, view, obj):
        cafe = obj.cafe
        return get_free_is_auth_with_perm(request, cafe, 'cafepay.can_manage_table')


class CanManageTableProduct(permissions.BasePermission):
    """
        check if product exists on the table or not
        checks happen on DELETE  method
    """

    def has_permission(self, request, view):
        table = get_object_or_404(Table, pk=view.kwargs.get('table_id'))
        product = get_object_or_404(Product, pk=view.kwargs.get('product_id'))

        if table.cafe == product.cafe:
            if request.method == 'DELETE':
                if table.active_bill and table.active_bill.has_product(product):
                    return True
                return False
            return True
        return False


class CanSeparateTable(permissions.BasePermission):
    """
        check if more than one table remain in the join after separation
    """

    def has_permission(self, request, view):
        table = get_object_or_404(Table, pk=view.kwargs.get('table_id'))

        if table.active_join:
            join = table.get_or_create_join
            return len(join.bills.all()) > 1
        return False


class CanJoinORTransferTables(permissions.BasePermission):
    """
        Check if two tables are from the same cafe
    """

    def has_permission(self, request, view):
        table_x = get_object_or_404(Table, pk=view.kwargs.get('table_x'))
        table_y = get_object_or_404(Table, pk=view.kwargs.get('table_y'))

        if table_x != table_y:
            return table_x.cafe == table_y.cafe
        return False
