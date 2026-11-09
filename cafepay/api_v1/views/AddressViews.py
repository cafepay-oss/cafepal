from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers

from cafepay.api_v1.permissions import IsLoggedIn, IsStaff, IsElevatedUser
from cafepay.api_v1.serializers.AddressSerializers import CityDetailedSerializer, UserProfileAddressSerializer, \
    UserProfileAddressCreateSerializer, CafeRegionDetailedSerializer, CafeRegionCRUDSerializer, CitySerializer, \
    RegionSerializer, CafeRegionBulkCreateSerializer, CafeRegionCRUDWithCafeSerializer
from cafepay.models import City, UserProfileAddress, Cafe, CafeRegionPrice, Region


class CityListView(generics.ListAPIView):
    serializer_class = CityDetailedSerializer
    queryset = City.objects.all()


class UserProfileAddressCreate(generics.CreateAPIView):
    permission_classes = (IsLoggedIn,)

    serializer_class = UserProfileAddressCreateSerializer

    def perform_create(self, serializer):
        serializer.save(user_profile=self.request.user.user_profile)


class UserProfileAddressRUD(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsLoggedIn,)
    serializer_class = UserProfileAddressCreateSerializer

    def get_object(self):
        _pk = self.kwargs.get('address_id')
        _user_profile = self.request.user.user_profile
        try:
            return _user_profile.addresses.get(pk=_pk)
        except UserProfileAddress.DoesNotExist:
            raise Http404()


class CafeRegionCreateView(generics.CreateAPIView):
    permission_classes = (IsStaff,)
    serializer_class = CafeRegionCRUDSerializer

    def perform_create(self, serializer):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        serializer.save(cafe=cafe)


class CafeRegionPriceBulkCreateView(generics.CreateAPIView):
    permission_classes = (IsStaff,)
    serializer_class = CafeRegionBulkCreateSerializer

    def perform_create(self, serializer):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))

        with transaction.atomic():
            errors = self.create_cafe_region_prices(cafe, serializer)
            if errors:
                raise serializers.ValidationError({'errors': errors})

    def create_cafe_region_prices(self, cafe, serializer):
        errors = []
        for cafe_region in serializer.validated_data.get('region_prices'):
            data = self.get_serializer_data(cafe, cafe_region)

            _errors = self.save_serializer(data)
            if _errors:
                errors.append(_errors)
        return errors

    @staticmethod
    def save_serializer(data):
        """
        :param data:
        :return: an error object, if any
        """
        serializer = CafeRegionCRUDWithCafeSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return {}
        else:
            return {
                'data': data,
                'errors': serializer.errors
            }

    @staticmethod
    def get_serializer_data(cafe, cafe_region):
        data = {
            'region': cafe_region.get('region').pk,
            'price': cafe_region.get('price'),
            'cafe': cafe.pk
        }
        return data


class CafeRegionRUDView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsStaff,)
    serializer_class = CafeRegionCRUDSerializer
    queryset = CafeRegionPrice.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'region_price_id'


class CafeRegionListView(generics.ListAPIView):
    permission_classes = (IsStaff,)
    serializer_class = CafeRegionCRUDSerializer

    def get_queryset(self):
        return CafeRegionPrice.objects.filter(cafe__pk=self.kwargs.get('cafe_id'))


class CityCreateView(generics.CreateAPIView):
    permission_classes = (IsElevatedUser,)
    serializer_class = CitySerializer


class CityRUDView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsElevatedUser,)
    serializer_class = CitySerializer

    queryset = City.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'city_id'


class RegionCreateView(generics.CreateAPIView):
    permission_classes = (IsElevatedUser,)
    serializer_class = RegionSerializer


class RegionCreateRUDView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (IsElevatedUser,)
    serializer_class = RegionSerializer

    queryset = Region.objects.all()
    lookup_field = 'pk'
    lookup_url_kwarg = 'region_id'


class RegionListView(generics.ListAPIView):
    serializer_class = RegionSerializer

    def get_queryset(self):
        return Region.objects.filter(city__pk=self.kwargs.get('city_id'))
