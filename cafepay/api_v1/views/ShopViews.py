from django.db.models import ProtectedError, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.translation import ugettext as _
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.generics import (CreateAPIView, ListAPIView,
                                     RetrieveUpdateAPIView,
                                     RetrieveUpdateDestroyAPIView,
                                     get_object_or_404, RetrieveAPIView)
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from cafepay.models import (Cafe, CafeUserProfileRelationRole, UserProfile, CafeUserProfileRelation, Gallery,
                            PushEndpoint, UserProfilePhoneVerification)
from cafepay.api_v1.permissions import CanManageRole, CanManageStaff, CanUpdateCafe, IsLoggedIn, IsStaff
from cafepay.api_v1.serializers.ShopSerializers import (CafeAddStaffSerializer,
                                                        CafeAddSerializer,
                                                        CafeStaffSerializer,
                                                        CafeBasicUpdateSerializer,
                                                        StaffRoleMemberSerializer,
                                                        StaffRoleSerializer,
                                                        CafeAuthTokenSerializer, CafeDeactivateStaffSerializer,
                                                        CafePendingStaffSerializer, StaffRoleUpdateSerializer,
                                                        CafeAuthInfoByTokenSerializer, CafeRetrieveSerializer,
                                                        GalleryAvatarSerializer, GallerySerializer,
                                                        GalleryGenericToggleSerializer, PushEndpointSerializer,
                                                        CafeListRetrieveSerializer)

from cafepay.api_v1.consts import CafeUserProfileRelationConsts, UserProfileConsts, InvoiceConsts


class CafeCreateView(CreateAPIView):
    """
        Create Cafe

        this endpoint creates a cafe with very basic info and no staff.

        after this, you may complete cafe info using several other endpoints.
    """

    serializer_class = CafeAddSerializer


class CafeUpdateView(RetrieveUpdateAPIView):
    """
        Cafe Update

        to update phones and emails use relevant api endpoints.

        permissions required: can_update_cafe.

    """

    permission_classes = (CanUpdateCafe,)
    serializer_class = CafeBasicUpdateSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_id'

    queryset = Cafe.objects.all()


class CafeAddImageToGalleryView(CreateAPIView):
    """
    Add Image to cafe Gallery
    """

    permission_classes = (IsStaff,)
    serializer_class = GallerySerializer

    def perform_create(self, serializer):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        serializer.save(cafe=cafe)


class CafeGallery(ListAPIView):
    """Cafe Gallery List """
    serializer_class = GallerySerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.shop_images.all()


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


class CafeListView(ListAPIView):
    """Cafe Gallery List """

    serializer_class = CafeListRetrieveSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Rank before pagination without fetching every cafe and wallet in Python.
        return Cafe.objects.annotate(
            deposit_total=Coalesce(Sum('wallet__invoice__amount',
                                      filter=Q(wallet__invoice__type=InvoiceConsts.DEPOSIT)), Value(0))
        ).order_by('deposit_total', 'pk')


class MarkCafeImageAsAvatar(RetrieveUpdateAPIView):
    """
    Mark the given image as avatar
    this automatically mark all the other images as not avatar
    """
    permission_classes = (IsStaff,)
    serializer_class = GalleryGenericToggleSerializer
    queryset = Gallery.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_image_id'

    def perform_update(self, serializer):
        # mark all as not avatar
        serializer.instance.cafe.shop_images.update(is_avatar=False)

        # mark current instance as avatar
        serializer.instance.is_avatar = True
        serializer.instance.save()


class MarkCafeImageAsHeader(RetrieveUpdateAPIView):
    """
    Mark the given image as header
    this automatically mark all the other images as not header
    """

    permission_classes = (IsStaff,)
    serializer_class = GalleryGenericToggleSerializer
    queryset = Gallery.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_image_id'

    def perform_update(self, serializer):
        # mark all as not avatar
        serializer.instance.cafe.shop_images.update(is_header=False)

        # mark current instance as avatar
        serializer.instance.is_header = True
        serializer.instance.save()


class CafeImageUpdateView(RetrieveUpdateDestroyAPIView):
    """
    Mark images as avatar
    """

    permission_classes = (IsStaff,)
    serializer_class = GalleryAvatarSerializer
    lookup_url_kwarg = 'cafe_image_id'
    lookup_field = 'pk'
    queryset = Gallery.objects.all()


class CafeBasicInfoView(RetrieveAPIView):
    """
        Cafe basic info
    """
    serializer_class = CafeRetrieveSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_id'

    queryset = Cafe.objects.all()


class AppendPushSubscription(CreateAPIView):
    """
    Append notification push subscription
    """

    permission_classes = (IsStaff,)
    serializer_class = PushEndpointSerializer

    def perform_create(self, serializer):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))

        # if push subscription with the given text exists, ignore it
        try:
            PushEndpoint.objects.get(text=serializer.validated_data.get('text'))
        except PushEndpoint.DoesNotExist:
            serializer.save(cafe=cafe)


class CafeBasicInfoByUsernameView(RetrieveAPIView):
    """
        Cafe basic info
    """
    serializer_class = CafeRetrieveSerializer

    lookup_field = 'username'
    lookup_url_kwarg = 'cafe_username'

    queryset = Cafe.objects.all()


class CafeAddStaffView(generics.CreateAPIView):
    """
        Add Staff

        add a user_profile to cafe with a specific role.

        role must belong to the cafe, or an 400 error will be returned.

        this user_profile will be called a staff on this cafe.

        status on this staff will be set to "pending".

        this staff is not allowed to perform any action in this cafe

        unless his/her status is set to "active".

        only the staff himself may accept and set it's status on this cafe-role to "active".

        permissions required: can_manage_staff.
    """

    permission_classes = (CanManageStaff,)
    serializer_class = CafeAddStaffSerializer

    def get_serializer_context(self):
        return {
            'request': self.request,
            'kwargs': self.kwargs
        }


class CafeDeactivateStaffView(generics.RetrieveUpdateAPIView):
    """
        Deactivate Staff

        Deactivate a given staff.

        deactivating a staff results in.

        denial of all permissions of that staff on this cafe.

        permissions required: can_manage_staff
    """

    permission_classes = (CanManageStaff,)
    serializer_class = CafeDeactivateStaffSerializer

    lookup_url_kwarg = 'staff_id'
    lookup_field = 'pk'

    def get_queryset(self):
        return CafeUserProfileRelation.objects.filter(role__cafe__pk=self.kwargs.get('cafe_id'))

    def perform_update(self, serializer):
        serializer.save(status=CafeUserProfileRelationConsts.REMOVED)


class CafeStaffDetailView(generics.RetrieveAPIView):
    """
        Staff Detail

        Detailed information about staff of the given cafe.

        if staff status is not verified a 404 error will be returned.

        permissions required: can_manage_staff
    """

    permission_classes = (CanManageStaff,)
    serializer_class = CafeStaffSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'staff_id'

    def get_queryset(self):
        return CafeUserProfileRelation. \
            objects.filter(role__cafe__pk=self.kwargs.get('cafe_id'),
                           status=CafeUserProfileRelationConsts.VERIFIED)


class CafeStaffListView(generics.ListAPIView):
    """
        Cafe Staff List.

        list of active and removed staff of the cafe.

        to get a list of pending staffs use the appropriate endpoint.

        permissions required: can_manage_staff.
    """

    permission_classes = (CanManageStaff,)
    serializer_class = CafeStaffSerializer

    def get_queryset(self):
        return CafeUserProfileRelation. \
            objects.filter(role__cafe__pk=self.kwargs.get('cafe_id'),
                           status__in=[CafeUserProfileRelationConsts.VERIFIED,
                                       CafeUserProfileRelationConsts.REMOVED]).distinct()


class CafePendingStaffListView(generics.ListAPIView):
    """
        list of pending staff of the cafe.

        permissions required: can_manage_staff.
    """

    permission_classes = (CanManageStaff,)
    serializer_class = CafePendingStaffSerializer

    def get_queryset(self):
        return CafeUserProfileRelation. \
            objects.filter(role__cafe__pk=self.kwargs.get('cafe_id'),
                           status=CafeUserProfileRelationConsts.PENDING).distinct()


class UserProfilePhoneNotFound(Exception):
    pass


class InvalidVerificationCode(Exception):
    payload = None  # any extra info about the exception


class CafeAuthTokenView(CreateAPIView):
    """
        Cafe Auth token.

        Obtain token of a user if is a staff in some cafe.

        a list of cafes for this profile will be returned.
    """

    serializer_class = CafeAuthTokenSerializer

    def create(self, request, *args, **kwargs):
        result = UserProfilePhoneVerification.objects.consume(
            request.data.get('phone_number'), request.data.get('password'))
        if result['status'] == 404:
            return Response({'detail': _('Phone number not found')}, status=status.HTTP_404_NOT_FOUND)
        if result['status'] == 403:
            return Response({'detail': _('Invalid verification code'),
                             'allowed_retry_times': result['allowed_retry_times']},
                            status=status.HTTP_403_FORBIDDEN)
        return Response(self.get_serializer_class()(instance=result['profile']).data)


class CafeAuthInfoByTokenView(RetrieveAPIView):
    """
    Auth info of the logged in user

    logged in user
    """
    permission_classes = (IsLoggedIn,)
    serializer_class = CafeAuthInfoByTokenSerializer

    def get_object(self):
        return self.request.user.user_profile


class CafeCreateRole(CreateAPIView):
    """
        Add role to cafe

        duplicate roles will raise error.

        required permissions: can_manage_role
    """

    permission_classes = (CanManageRole,)
    serializer_class = StaffRoleSerializer

    def get_serializer_context(self):
        return {
            'request': self.request,
            'kwargs': self.kwargs
        }


class CafeListRole(ListAPIView):
    """
        List Cafe Roles.

      required permissions: can_manage_role
    """

    permission_classes = (CanManageRole,)
    serializer_class = StaffRoleSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.staff_roles.all()


class CafeRUDRole(RetrieveUpdateDestroyAPIView):
    """
        retrieve update delete role.

        required permissions: can_manage_role.
    """

    permission_classes = (CanManageRole,)
    serializer_class = StaffRoleUpdateSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'role_id'

    queryset = CafeUserProfileRelationRole.objects.all()

    def delete(self, request, *args, **kwargs):
        try:
            self.get_object().delete()
        except ProtectedError:
            return Response({'error': _('Only empty roles can be deleted')}, status=status.HTTP_400_BAD_REQUEST)
