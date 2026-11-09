from rest_framework import serializers

from cafepay.api_v1.serializers.UserProfileSerializrs import CharacterFieldSerializer
from cafepay.models import Printer, PrinterJob, PrinterType


class PrinterTypeSerializer(serializers.ModelSerializer):

    class Meta:
        model = PrinterType
        fields = ['pk', 'type', 'get_type_display', ]


class PrinterSerializer(serializers.ModelSerializer):
    """Printer info serializer"""

    the_types = PrinterTypeSerializer(many=True, read_only=True, source='types')
    the_groups = CharacterFieldSerializer(many=True, read_only=True, source='groups')

    class Meta:
        model = Printer
        fields = ['pk', 'name', 'uid', 'types', 'policy', 'the_types',
                  'groups', 'the_groups', 'description',
                  'display_name', 'width', 'is_on']


class PrintRawDataSerializer(serializers.ModelSerializer):
    """raw data print"""

    printer = PrinterSerializer(read_only=True)

    class Meta:
        model = PrinterJob
        fields = ['pk', 'raw_data', 'printer', 'is_done', 'description']


class CafePrinterJobsSerializer(serializers.ModelSerializer):
    """Active printer jobs"""
    jobs = PrintRawDataSerializer(many=True, source='active_jobs')

    class Meta:
        model = Printer
        fields = ['pk', 'uid', 'jobs', 'name', 'display_name', 'width', 'description']
