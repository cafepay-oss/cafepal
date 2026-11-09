import datetime

from django.core.validators import RegexValidator
from django.utils.translation import gettext as _
from rest_framework import serializers


class TimeParamsSerializer(serializers.Serializer):
    """
            start date must be persian format
            times should be +4:30 UTC
    """

    start_date = serializers.CharField(validators=[
        RegexValidator(r'^[1][1-4][0-9]{2}\/((0[1-6]\/(0[1-9]|[1-2][0-9]|3[0-1]))|(0[7-9]\/(0[1-9]|[1-2][0-9]|30))|('
                       r'1[0-1]\/(0[1-9]|[1-2][0-9]|30))|(12\/(0[1-9]|[1-2][0-9])))')
    ])

    end_date = serializers.CharField(validators=[
        RegexValidator(r'^[1][1-4][0-9]{2}\/((0[1-6]\/(0[1-9]|[1-2][0-9]|3[0-1]))|(0[7-9]\/(0[1-9]|[1-2][0-9]|30))|('
                       r'1[0-1]\/(0[1-9]|[1-2][0-9]|30))|(12\/(0[1-9]|[1-2][0-9])))')
    ])

    start_time = serializers.TimeField(write_only=True)
    end_time = serializers.TimeField(write_only=True)

    @staticmethod
    def validate_start_date(start_date):
        return start_date.replace('/', '-')

    @staticmethod
    def validate_end_date(end_date):
        return end_date.replace('/', '-')
