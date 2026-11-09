from rest_framework import generics

from cafepay.api_v1.serializers.DownloadFileSerializer import DownloadFileRetrieveSerializer
from cafepay.models import DownloadFile


class DownloadFilesListView(generics.ListAPIView):
    """
    List of Downloadable utilities
    """
    serializer_class = DownloadFileRetrieveSerializer
    queryset = DownloadFile.objects.all()
