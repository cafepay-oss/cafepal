from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.pagination import PageNumberPagination

from cafepay.api_v1.permissions import IsElevatedUser
from cafepay.api_v1.serializers.RawLogSerializers import RawLogSerializer
from cafepay.models import RawLog


class RawLogCreateView(CreateAPIView):
    serializer_class = RawLogSerializer


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


class RawLogListView(ListAPIView):
    permission_classes = (IsElevatedUser, )
    serializer_class = RawLogSerializer
    pagination_class = StandardResultsSetPagination
    queryset = RawLog.objects.all()
