"""Password login for the isolated local recovery stack."""
from django.conf import settings
from django.contrib.auth import authenticate
from django.http import Http404
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from cafepay.api_v1.serializers.ShopSerializers import CafeAuthTokenSerializer
from cafepay.models import UserProfile


class LocalLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=255, trim_whitespace=False, write_only=True)


class LocalLoginView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request):
        if not getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False):
            raise Http404
        credentials = LocalLoginSerializer(data=request.data)
        credentials.is_valid(raise_exception=True)
        user = authenticate(request=request, **credentials.validated_data)
        profile = UserProfile.objects.filter(django_user=user).first() if user else None
        if profile is None:
            return Response({'detail': 'Invalid local credentials.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CafeAuthTokenSerializer(profile, context={'request': request}).data)
