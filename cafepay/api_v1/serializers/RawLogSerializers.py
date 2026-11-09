from rest_framework import serializers
from cafepay.models import RawLog


class RawLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawLog
        fields = ['pk', 'text']
