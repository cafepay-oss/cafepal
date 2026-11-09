from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext as _
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import APIException
from rest_framework.generics import CreateAPIView, RetrieveUpdateAPIView, RetrieveAPIView, ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from cafepal import settings
from cafepal.secret import DEMO
from cafepay.api_v1.consts import UserProfileConsts, InvoiceConsts
from cafepay.api_v1.permissions import IsLoggedIn, IsElevatedUser, IsStaff
from cafepay.api_v1.serializers.JoinSerializers import JoinSimpleSerializer
from cafepay.api_v1.serializers.UserProfileSerializrs import UserProfileCRSerializer, UserProfileUpdateSerializer, \
    UserProfilePhoneVerificationSerializer, SendCafepayCodeSerializer, UserProfileSetPassword, \
    UserProfileCafePrivateSerializer, UserProfileWalletSerializer, AdminUserProfileCRSerializer, \
    UserProfileVerifySerializer, TempTokenSerializer, UseTempTokenSerializer
from cafepay.api_v1.serializers.WalletAndInvoiceSerializers import ChargeWalletInvoiceSerializer
from cafepay.api_v1.views.ReportViews import StandardResultsSetPagination
from cafepay.models import UserProfilePhoneVerification, UserProfile, TableJoin, TempToken


class UserProfileCreateView(CreateAPIView):
    """
        Add User Profile.

        Creates a user profile and sets its verification status to "pending"

        an sms containing a verification code will be sent.
    """

    serializer_class = UserProfileCRSerializer

    def perform_create(self, serializer):
        user_profile = serializer.save()
        UserProfilePhoneVerification.objects.create(user_profile=user_profile)


class UserProfileGetOrCreateView(CreateAPIView):
    """
        Add User Profile as a cafe staff.

    """

    permission_classes = (IsStaff,)

    serializer_class = UserProfileCRSerializer

    def serialize(self, user_profile):
        return self.serializer_class(instance=user_profile).data

    def create(self, request, *args, **kwargs):

        # if a user profile with the given phone number exists, return it
        try:
            user_profile = UserProfile.objects.get(phone_number=request.data.get('phone_number'))
        except UserProfile.DoesNotExist:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            user_profile = serializer.save(verification_status=UserProfileConsts.VERIFIED)

        return Response(self.serialize(user_profile))


class UserProfileSetPasswordView(generics.UpdateAPIView):
    """
        Set password.

        Set password for the first time.

        if already has password, error will be raised.
    """
    permission_classes = (IsLoggedIn,)
    serializer_class = UserProfileSetPassword

    def get_object(self):
        return self.request.user.user_profile


class UserProfileRUView(RetrieveUpdateAPIView):
    """
        User Profile Retrieve.

        Currently logged in User can retrieve and update itself.

        they cannot change their phone number.
    """

    serializer_class = UserProfileUpdateSerializer
    permission_classes = (IsLoggedIn,)

    def get_object(self):
        return self.request.user.user_profile


class UserProfileVerifyView(RetrieveUpdateAPIView):
    """
        User profile verification
    """

    serializer_class = UserProfileVerifySerializer
    permission_classes = [IsElevatedUser, ]

    queryset = UserProfile.objects.all()

    lookup_url_kwarg = 'user_id'
    lookup_field = 'pk'

    def perform_update(self, serializer):
        serializer.save(verification_status=UserProfileConsts.VERIFIED)


class UserProfileWalletView(RetrieveAPIView):
    """Wallet info of the currently logged in user"""

    permission_classes = (IsLoggedIn,)
    serializer_class = UserProfileWalletSerializer

    def get_object(self):
        return self.request.user.user_profile


class UserProfileChargeWallet(CreateAPIView):
    """Create a charge wallet invoice for
    the currently logged in user"""

    permission_classes = (IsLoggedIn,)
    serializer_class = ChargeWalletInvoiceSerializer

    def perform_create(self, serializer):
        user_profile = self.request.user.user_profile
        data = {
            'wallet': user_profile.wallet,
            'type': InvoiceConsts.DEPOSIT,
            'use_default_gate': False,
            'payment_gate': "ZIBAL",
            'merchant': 'zibal',
            'tag': InvoiceConsts.CHARGE_WALLET
        }
        serializer.save(**data)


class OrderHistoryView(ListAPIView):
    """
        Order history of the logged in user

        required permission: isLoggedIn
    """

    serializer_class = JoinSimpleSerializer
    permission_classes = (IsLoggedIn,)
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        up = self.request.user.user_profile
        return TableJoin.objects.filter(
            Q(bills__bill_pbrs__user_profile=up) |
            Q(bills__bill_pbrs__invoices__wallet__user_profile=up)
        ).distinct().order_by('-datetime')


class UserProfileCafePrivateRView(RetrieveAPIView):
    """
        User Profile Retrieve By private id.

        anyone with private id
    """

    serializer_class = UserProfileCafePrivateSerializer
    permission_classes = (IsLoggedIn,)
    queryset = UserProfile.objects.all()

    lookup_url_kwarg = 'private_id'
    lookup_field = 'private_id'


class UserProfileAuthTokenView(generics.GenericAPIView):
    """
        User Profile Auth token.

        match phone number and verification code.

        return user token on success.
    """

    serializer_class = UserProfilePhoneVerificationSerializer

    def post(self, request, *args, **kwargs):
        phone = request.data.get('phone_number')
        code = request.data.get('code')

        result = UserProfilePhoneVerification.objects.consume(phone, code)
        if result['status'] == 404:
            return Response({'detail': _('Phone number not found')}, status=status.HTTP_404_NOT_FOUND)
        if result['status'] == 403:
            return Response({'detail': _('Invalid verification code'),
                             'allowed_retry_times': result['allowed_retry_times']},
                            status=status.HTTP_403_FORBIDDEN)
        return Response(self.serializer_class(instance=result['profile']).data)


class SendCafepayCode(generics.GenericAPIView):
    """
        Send Code.

        Send verification code.

        phone must have been registered before.

        if send failed respond with wait time.
    """

    serializer_class = SendCafepayCodeSerializer

    @staticmethod
    def get_user_profile(phone_number):
        try:
            return UserProfile.objects.get(phone_number=phone_number)
        except UserProfile.DoesNotExist:
            ups = UserProfileCRSerializer(data={'phone_number': phone_number})
            ups.is_valid(raise_exception=True)
            user_profile = ups.save()
            return user_profile

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        upv = UserProfilePhoneVerification.objects. \
            create(user_profile=self.get_user_profile(serializer.data.get('phone_number')))

        if upv['status'] != 201:
            return Response({'detail': _("Code not sent"), 'wait': upv['wait']}, status=upv['status'])

        if DEMO:
            return Response({"code": upv['obj'].code})

        return Response({'detail': _("Code sent")})


class AdminUserProfileCreateView(generics.CreateAPIView):
    """
    Create a user profile

    this endpoint does not require phone verification
    password is required
    """
    permission_classes = (IsElevatedUser,)

    serializer_class = AdminUserProfileCRSerializer


class CreateTempTokenView(generics.CreateAPIView):
    """
    Create a temp token

    Used for cross domain authentication
    """
    permission_classes = (IsLoggedIn,)

    serializer_class = TempTokenSerializer

    def perform_create(self, serializer):
        serializer.save(user_profile=self.request.user.user_profile)


class UseTempTokenView(generics.UpdateAPIView):
    """
    User a temp token

    Used for cross domain authentication
    """
    serializer_class = UseTempTokenSerializer

    def put(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        temp_token = get_object_or_404(
            TempToken,
            host=serializer.data.get('host'),
            token=serializer.data.get('token')
        )
        if temp_token.used:
            return Response({'error': _('Temp token is used')}, status=403)
        token = temp_token.user_profile.token
        temp_token.used = True
        temp_token.save()
        return Response({'token': token}, status=200)

