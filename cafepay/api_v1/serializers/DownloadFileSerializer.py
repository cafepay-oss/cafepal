from rest_framework import serializers

from cafepay.models import DownloadFile


class DownloadFileRetrieveSerializer(serializers.ModelSerializer):

    class Meta:
        model = DownloadFile
        fields = ['pk', 'title', 'file', 'description']
