from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from cafepay.api_v1.modules.card_transfer import start_transfer, submit_receipt, review_transfer
from cafepay.api_v1.permissions import IsLoggedIn, IsStaff, CanUpdateCafe, has_perm_in_cafe, ANY
from cafepay.api_v1.serializers.CardTransferSerializers import (
    CardTransferSerializer, CardTransferSettingsSerializer, CardTransferReviewSerializer)
from cafepay.models import Cafe, CardTransfer


class CardTransferSettingsView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsLoggedIn, IsStaff, CanUpdateCafe)
    serializer_class = CardTransferSettingsSerializer
    queryset = Cafe.objects.all()
    lookup_url_kwarg = 'cafe_id'

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [IsLoggedIn(), IsStaff()]
        return super().get_permissions()


class CardTransferStartView(APIView):
    permission_classes = (IsLoggedIn,)

    def post(self, request, join_id):
        transfer = start_transfer(join_id, request.user.user_profile)
        return Response(CardTransferSerializer(transfer).data)


class CardTransferDetailView(APIView):
    permission_classes = (IsLoggedIn,)

    def get_transfer(self, request, transfer_uuid):
        transfer = get_object_or_404(CardTransfer.objects.select_related('cafe', 'customer', 'join'), uuid=transfer_uuid)
        if (transfer.customer_id != request.user.user_profile.pk and
                not has_perm_in_cafe(request, transfer.cafe, ANY)):
            raise NotFound()
        return transfer

    def get(self, request, transfer_uuid):
        return Response(CardTransferSerializer(self.get_transfer(request, transfer_uuid)).data)


class CardTransferReceiptView(CardTransferDetailView):
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request, transfer_uuid):
        transfer = self.get_transfer(request, transfer_uuid)
        if not transfer.receipt:
            raise NotFound()
        response = FileResponse(transfer.receipt.open('rb'), content_type='image/png')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    def post(self, request, transfer_uuid):
        transfer = submit_receipt(self.get_transfer(request, transfer_uuid),
                                  request.user.user_profile, request.FILES.get('receipt'))
        return Response(CardTransferSerializer(transfer).data)


class CardTransferReviewView(CardTransferDetailView):
    def post(self, request, transfer_uuid):
        transfer = self.get_transfer(request, transfer_uuid)
        if not has_perm_in_cafe(request, transfer.cafe, ANY):
            raise PermissionDenied()
        serializer = CardTransferReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = review_transfer(transfer, request.user.user_profile, **serializer.validated_data)
        return Response(CardTransferSerializer(transfer).data)


class CardTransferPagination(PageNumberPagination):
    page_size = 50


class CardTransferListView(generics.ListAPIView):
    permission_classes = (IsLoggedIn, IsStaff)
    serializer_class = CardTransferSerializer
    pagination_class = CardTransferPagination

    def get_queryset(self):
        queryset = CardTransfer.objects.filter(cafe_id=self.kwargs['cafe_id']).exclude(
            status__in=[CardTransfer.DRAFT, CardTransfer.EXPIRED]).select_related('customer', 'join')
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset.order_by('submitted_at', 'pk') if status == CardTransfer.SUBMITTED else queryset
