from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from cafepay.api_v1.consts import UserProfileConsts
from cafepay.api_v1.serializers.AddressSerializers import UserProfileAddressDetailedSerializer
from cafepay.api_v1.serializers.WalletAndInvoiceSerializers import WalletSerializer
from cafepay.models import CharacterField, UserProfile, Wallet, ProductBillRelation, TempToken

from django.utils.translation import gettext as _


class CharacterFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = CharacterField
        fields = ['pk', 'title', 'type', 'is_delete', 'menu']


class UserProfilePhoneVerificationSerializer(serializers.ModelSerializer):
    """
        Used for verifying phone numbers
    """

    phone_number = serializers.CharField(max_length=12)
    code = serializers.CharField(max_length=10, write_only=True)

    class Meta:
        model = UserProfile
        fields = [
            'code',
            'pk',
            'full_name',
            'first_name',
            'last_name',
            'balance',
            'card_number',
            'date_joined',
            'email', 'phone_number', 'token'
        ]

        extra_kwargs = {
            'full_name': {'read_only': True},
            'first_name': {'read_only': True},
            'last_name': {'read_only': True},
            'date_joined': {'read_only': True},
            'balance': {'read_only': True},
            'email': {'read_only': True},
        }


class UserProfileCRSerializer(serializers.ModelSerializer):
    """
        Create a user profile
        password is by default not required
        you can enforce password by passing required_password = True to the serializer
    """

    def __init__(self, *args, **kwargs):
        require_password = kwargs.pop('require_password', False)

        super(UserProfileCRSerializer, self).__init__(*args, **kwargs)

        if require_password:
            self.fields['password'].required = True

    password = serializers.CharField(max_length=255, required=False, write_only=True)

    class Meta:
        model = UserProfile
        fields = ['pk',
                  'full_name',
                  'first_name',
                  'last_name',
                  'balance',
                  'card_number',
                  'email', 'national_code',
                  'phone_number', 'password']

    def create(self, validated_data):
        with transaction.atomic():
            # create a django user for internal usage
            django_user = User.objects.create_user(username=validated_data.get('phone_number'),
                                                   password=validated_data.pop('password', None))
            # create an E-Wallet
            w = Wallet.objects.create()
            user_profile = UserProfile.objects.create(**validated_data, django_user=django_user, wallet=w)
            return user_profile


class AdminUserProfileCRSerializer(serializers.ModelSerializer):
    """
        Create a user profile as an admin user
        password is required
    """

    password = serializers.CharField(max_length=255, required=True, write_only=True)

    class Meta:
        model = UserProfile
        fields = ['pk',
                  'full_name',
                  'first_name',
                  'last_name',
                  'balance',
                  'card_number',
                  'email', 'national_code',
                  'phone_number', 'password']

    def create(self, validated_data):
        with transaction.atomic():
            # create a django user for internal usage
            django_user = User.objects.create_user(username=validated_data.get('phone_number'),
                                                   password=validated_data.pop('password', None))
            # create an E-Wallet
            w = Wallet.objects.create()
            user_profile = UserProfile.objects.create(**validated_data,
                                                      django_user=django_user,
                                                      wallet=w,
                                                      verification_status=UserProfileConsts.VERIFIED)

            return user_profile


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    active_table_uuid = serializers.SerializerMethodField()
    addresses = UserProfileAddressDetailedSerializer(many=True, read_only=True, source='base_addresses')

    class Meta:
        model = UserProfile
        fields = ['pk',
                  'full_name',
                  'first_name',
                  'last_name',
                  'balance',
                  'date_joined',
                  'card_number',
                  'address',
                  'active_table_uuid',
                  'email', 'national_code',
                  'has_usable_password',
                  'addresses',
                  'active_address',
                  'phone_number', 'verification_status',
                  'get_verification_status_display']
        extra_kwargs = {
            'phone_number': {'read_only': True},
            'date_joined': {'read_only': True},
            'verification_status': {'read_only': True}
        }

    @staticmethod
    def get_active_table_uuid(user_profile):
        return user_profile.active_preorder


class UserProfileVerifySerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['pk', 'get_verification_status_display']


class UserProfileWalletSerializer(serializers.ModelSerializer):
    """Serializer wallet and transactions data"""
    wallet = WalletSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ['pk', 'wallet']


class UserProfileCafePrivateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['pk',
                  'full_name',
                  'first_name',
                  'last_name',
                  'balance',
                  'card_number',
                  'date_joined',
                  'email', 'phone_number']


class UserProfileSetPassword(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = UserProfile
        fields = ['pk', 'password']

    # todo: password validation
    def validate(self, attrs):
        if self.instance and not self.instance.django_user.has_usable_password():
            return attrs
        raise serializers.ValidationError(_("Password already set"))

    def update(self, instance, validated_data):
        instance.django_user.set_password(validated_data.get('password'))
        instance.django_user.save()

        return instance


class SendCafepayCodeSerializer(serializers.Serializer):
    """
        Used to fetch phone number and send verification code to it
        if a user profile with the given phone number exists then only
        a verification code will be sent to it
        if not, one will be created
    """

    phone_number = serializers.CharField(validators=[
        RegexValidator(
            regex=r"^(\+98|0)?9\d{9}$",
            message=_("Enter a valid phone number"),
            code='invalid_phone_number'
        ),
    ])


class TempTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = TempToken
        fields = [
            'pk',
            'user_profile',
            'token',
            'host',
        ]
        read_only_fields = ('user_profile', 'token')


class UseTempTokenSerializer(serializers.Serializer):
    host = serializers.CharField(max_length=255)
    token = serializers.UUIDField()
