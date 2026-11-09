from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework import serializers

from cafepay.api_v1.consts import CharacterFieldConsts, CafeUserProfileRelationConsts
from cafepay.api_v1.helpers import OverallRatingField
from cafepay.api_v1.serializers.AddressSerializers import CafeRegionDetailedSerializer
from cafepay.api_v1.serializers.CafePrinterSerializer import PrinterSerializer
from cafepay.api_v1.serializers.UserProfileSerializrs import CharacterFieldSerializer, UserProfileCRSerializer
from cafepay.models import Cafe, CharacterField, UserProfile, Wallet, CafeUserProfileRelation, \
    CafeUserProfileRelationRole, Printer, Gallery, PushEndpoint, TableToken
from rest_framework.authtoken.models import Token


class CafeAddSerializer(serializers.ModelSerializer):
    # todo: endpoint to add shop emails and phones
    # todo: endpoint to add staff/creator to cafe
    # todo: cafe update endpoint

    class Meta:
        model = Cafe
        fields = ['pk', 'name', 'description', 'address', 'is_menu_only',
                  'payment_only',
                  'has_delivery',
                  'payment_first']

    def create(self, validated_data):
        with transaction.atomic():
            # get validated admin data
            cafe = Cafe.objects.create(**validated_data, wallet=Wallet.objects.create())

            # Provision new cafes during creation, before their first public read.
            cafe.get_or_create_token(TableToken.MENU_ONLY)

            # create a default "creator" role

            CafeUserProfileRelationRole.objects.create(
                code_name="creator",
                cafe=cafe,
                display_name="Creator"
            )

            return cafe


class CafeBasicSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(read_only=True)
    header_image = serializers.ImageField(read_only=True)
    delivery_regions = CafeRegionDetailedSerializer(many=True)

    class Meta:
        model = Cafe
        fields = ['pk', 'name', 'avatar', 'cafepay_fee',
                  'payment_first', 'payment_only', 'phone', 'card_transfer_enabled',
                  'is_closed', 'fee_payer', 'header_image',
                  'delivery_regions',
                  'has_delivery',
                  'mean_ready_duration']


class StaffRoleRawSerializer(serializers.ModelSerializer):
    class Meta:
        model = CafeUserProfileRelationRole
        fields = ['pk', 'display_name', 'code_name', ]


class UserProfileCafeRelationCafeSerializer(serializers.ModelSerializer):
    cafe = CafeBasicSerializer(read_only=True, source="role.cafe")
    role = StaffRoleRawSerializer(read_only=True)

    class Meta:
        model = CafeUserProfileRelation
        fields = ['pk', 'cafe', 'status', 'get_status_display', 'role']


class LocalAdminCafeAccessMixin:
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if (getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False) and
                instance.django_user.is_superuser):
            # Return all cafes without creating staff records in restored data.
            data['cafe_relations'] = [{
                'pk': cafe.pk,
                'cafe': CafeBasicSerializer(cafe, context=self.context).data,
                'status': CafeUserProfileRelationConsts.VERIFIED,
                'get_status_display': _('Verified'),
                'role': {'pk': None, 'display_name': 'Local administrator', 'code_name': 'creator'},
            } for cafe in Cafe.objects.order_by('pk')]
        return data


class CafeAuthTokenSerializer(LocalAdminCafeAccessMixin, serializers.ModelSerializer):
    phone_number = serializers.CharField(max_length=255, write_only=True)
    password = serializers.CharField(max_length=255, write_only=True)

    token = serializers.SerializerMethodField(read_only=True)
    cafe_relations = UserProfileCafeRelationCafeSerializer(read_only=True, many=True, source="cafe_relations_no_sms")

    class Meta:
        model = UserProfile
        fields = ['phone_number', 'password', 'token', 'cafe_relations']

    @staticmethod
    def get_token(instance):
        token, created = Token.objects.get_or_create(user=instance.django_user)
        return token.key


class CafeAuthInfoByTokenSerializer(LocalAdminCafeAccessMixin, serializers.ModelSerializer):
    token = serializers.SerializerMethodField(read_only=True)
    cafe_relations = UserProfileCafeRelationCafeSerializer(read_only=True, many=True)

    class Meta:
        model = UserProfile
        fields = ['token', 'cafe_relations']

    @staticmethod
    def get_token(instance):
        token, created = Token.objects.get_or_create(user=instance.django_user)
        return token.key


class CafeAddStaffSerializer(serializers.ModelSerializer):
    user_profile = serializers.SlugRelatedField(
        queryset=UserProfile.objects.all(),
        slug_field='phone_number',
        help_text=_("phone number of the intended user profile"))

    class Meta:
        model = CafeUserProfileRelation
        fields = ['pk', 'user_profile', 'role']

    def validate_role(self, role):
        cafe_pk = self.context.get('kwargs').get('cafe_id')
        cafe = Cafe.objects.get(pk=cafe_pk)
        if role.cafe != cafe:
            raise serializers.ValidationError(_("Invalid role"))
        return role


class CafeDeactivateStaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = CafeUserProfileRelation
        fields = ['pk', 'status', 'get_status_display']
        extra_kwargs = {
            'status': {'read_only': True}
        }


class StaffRoleSerializer(serializers.ModelSerializer):
    cafe = serializers.HiddenField(default=0)

    class Meta:
        model = CafeUserProfileRelationRole
        fields = ['pk', 'cafe', 'display_name', 'code_name', ]

    def validate_cafe(self, cafe):
        return get_object_or_404(Cafe, pk=self.context.get('kwargs').get('cafe_id'))


class StaffRoleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CafeUserProfileRelationRole
        fields = ['pk', 'display_name', 'code_name', ]

    def validate_code_name(self, code_name):
        # duplicate code name in cafe check
        try:
            CafeUserProfileRelationRole.objects.get(Q(code_name=code_name)
                                                    & Q(cafe=self.instance.cafe)
                                                    & ~Q(pk=self.instance.pk))
            raise serializers.ValidationError(_("Duplicate code name"))
        except CafeUserProfileRelationRole.DoesNotExist:
            return code_name

    def validate(self, attrs):
        if not self.instance:
            raise serializers.ValidationError(_("This serializer may only be used for update"))

        return attrs


class StaffRoleMemberSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CafeUserProfileRelationRole
        fields = ['pk', 'cafe', 'display_name', 'code_name', 'members']

        extra_kwargs = {
            'cafe': {'read_only': True}
        }

    @staticmethod
    def get_members(instance):
        user_profiles = [cupr.user_profile for cupr in instance.cafe_relations.all()]
        return UserProfileCRSerializer(instance=user_profiles, many=True).data


class CafeStaffSerializer(serializers.ModelSerializer):
    user_profile = UserProfileCRSerializer()
    role = StaffRoleSerializer()

    class Meta:
        model = CafeUserProfileRelation
        fields = ['pk', 'user_profile', 'role', 'status', 'get_status_display']


class CafePendingStaffSerializer(serializers.ModelSerializer):
    role = StaffRoleSerializer()
    phone_number = serializers.ReadOnlyField(source='user_profile.phone_number')

    class Meta:
        model = CafeUserProfileRelation
        fields = ['pk', 'phone_number', 'role', 'status', 'get_status_display']


class GallerySerializer(serializers.ModelSerializer):
    class Meta:
        model = Gallery
        fields = ['pk', 'image', 'is_avatar', 'is_header', 'is_qr']


class GalleryAvatarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gallery
        fields = ['pk', 'is_avatar', 'image', 'is_header', 'is_qr']


class TableTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = TableToken
        fields = ['pk', 'token', 'type', 'status', 'has_delivery']


class CafeRetrieveSerializer(serializers.ModelSerializer):
    emails = CharacterFieldSerializer(many=True, read_only=True)
    phones = CharacterFieldSerializer(many=True, read_only=True)

    overall_rating = OverallRatingField(read_only=True)
    avatar = serializers.ImageField(read_only=True)
    header_image = serializers.ImageField(read_only=True)
    shop_images = GalleryAvatarSerializer(many=True, required=True, source="shop_images_filtered")

    preorder_token = TableTokenSerializer(read_only=True)
    menu_only_token = TableTokenSerializer(read_only=True)

    class Meta:
        model = Cafe
        fields = [
            'payment_only',
            'payment_first',
            'has_delivery',
            'pk', 'name', 'description', 'location', 'address',
            'phone', 'working_times', 'is_closed', 'instagram',
            'is_onsite',
            'cafepay_fee', 'fee_payer', 'menu_only_token', 'preorder_token',
            'short_description', 'is_menu_only', 'mean_ready_duration',
            'menu_prices_on', 'menu_items_on', 'emails', 'header_image',
            'phones', 'overall_rating', 'avatar', 'shop_images'
        ]

        extra_kwargs = {
            'is_menu_only': {'read_only': True}
        }


class TokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = TableToken
        fields = ['pk', 'type', 'status', 'token', 'has_delivery']


class CafeListRetrieveSerializer(serializers.ModelSerializer):
    overall_rating = OverallRatingField(read_only=True)
    avatar = serializers.ImageField(read_only=True)
    header_image = serializers.ImageField(read_only=True)
    shop_images = GalleryAvatarSerializer(many=True, required=True)

    preorder_token = TokenSerializer(read_only=True)
    menu_only_token = TokenSerializer(read_only=True)

    class Meta:
        model = Cafe
        fields = [
            'pk', 'name', 'description', 'location', 'address',
            'is_closed', 'is_onsite',
            'payment_first', 'payment_only',
            'menu_only_token', 'preorder_token',
            'short_description', 'mean_ready_duration',
            'header_image',
            'has_delivery',
            'is_active',
            'overall_rating', 'avatar', 'shop_images'
        ]

        extra_kwargs = {
            'is_menu_only': {'read_only': True}
        }


class PushEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushEndpoint
        fields = ['pk', 'text', 'keys']


class CafeBasicUpdateSerializer(serializers.ModelSerializer):
    printers = PrinterSerializer(many=True, read_only=True)
    push_endpoints = PushEndpointSerializer(many=True, read_only=True)

    preorder_token = TableTokenSerializer(read_only=True)
    menu_only_token = TableTokenSerializer(read_only=True)

    class Meta:
        model = Cafe
        fields = ['pk', 'name', 'description',
                  'instagram', 'short_description',
                  'payment_first', 'payment_only',
                  'cafepay_fee', 'fee_payer', 'is_onsite',
                  'push_endpoints', 'menu_only_token', 'preorder_token',
                  'is_menu_only', 'mean_ready_duration',
                  'has_delivery',
                  'phone', 'working_times', 'is_closed',
                  'location', 'address', 'printers']

        extra_kwargs = {
            'is_menu_only': {'read_only': True}
        }


class GalleryGenericToggleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gallery
        fields = ['pk', 'image', 'is_avatar', 'is_header', 'is_qr']

        extra_kwargs = {
            'image': {'read_only': True},
            'is_avatar': {'read_only': True},
            'is_header': {'read_only': True}
        }
