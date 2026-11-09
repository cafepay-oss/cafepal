from django.shortcuts import get_object_or_404
from rest_framework import generics

from cafepay.api_v1.permissions import IsStaff
from cafepay.api_v1.serializers.CafePhonesSerializers import CafeCharFieldSerializer
from cafepay.models import Cafe


class CafeCharFieldView(generics.CreateAPIView):
    """
    Create a char based field for a cafe

    types are:
    category
    phone number
    email
    """
    permission_classes = (IsStaff, )

    serializer_class = CafeCharFieldSerializer

    def perform_create(self, serializer):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        serializer.save(cafe=cafe, staff=self.request.user.user_profile)


