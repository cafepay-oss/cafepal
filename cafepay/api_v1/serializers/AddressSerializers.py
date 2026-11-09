from rest_framework import serializers

from cafepay.models import UserProfileAddress, Region, City, CafeRegionPrice


class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ['pk', 'name']


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ['pk', 'name', 'city', 'lat', 'lon']


class RegionDetailedSerializer(RegionSerializer):
    city = CitySerializer()


class UserProfileAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfileAddress
        fields = ['pk', 'region', 'address', 'user_profile', 'is_clone', 'cloned_from', 'lat', 'lon']


class UserProfileAddressCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfileAddress
        fields = ['pk', 'region', 'address', 'lat', 'lon']


class UserProfileAddressDetailedSerializer(UserProfileAddressSerializer):
    region = RegionDetailedSerializer()


class CafeRegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CafeRegionPrice
        fields = ['pk', 'region', 'cafe', 'price']


class CafeRegionDetailedSerializer(CafeRegionSerializer):
    region = RegionDetailedSerializer()


class CafeRegionCRUDSerializer(serializers.ModelSerializer):
    class Meta:
        model = CafeRegionPrice
        fields = ['pk', 'region', 'price']


class CafeRegionCRUDWithCafeSerializer(CafeRegionCRUDSerializer):
    class Meta(CafeRegionCRUDSerializer.Meta):
        fields = CafeRegionCRUDSerializer.Meta.fields + ['cafe']


class CafeRegionBulkCreateSerializer(serializers.Serializer):
    region_prices = CafeRegionCRUDSerializer(many=True)


class CityDetailedSerializer(CitySerializer):
    regions = RegionSerializer(many=True)

    class Meta(CitySerializer.Meta):
        fields = CitySerializer.Meta.fields + ['regions', ]
