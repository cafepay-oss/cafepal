from rest_framework import serializers

from cafepay.api_v1.helpers import convert_jalali_to_gregorian
from cafepay.api_v1.serializers.HelperSerializers import TimeParamsSerializer
from cafepay.models import Product, UserProfile
import datetime
from django.utils.translation import gettext as _


class ProductReportsSerializer(serializers.ModelSerializer):
    """
    Generate Product Reports
    """

    payment_info = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['pk', 'name', 'description',
                  'remaining',
                  'original_price', 'discount',
                  'price', 'payment_info',
                  'overall_rating',
                  ]

    def get_payment_info(self, product):
        date_info = self.context.get('date_info')

        start_date = date_info.get('start_date')
        end_date = date_info.get('end_date')
        start_time = date_info.get('start_time')
        end_time = date_info.get('end_time')

        date_info_dict = {
            'start_date': start_date,
            'end_date': end_date,
            'start_time': start_time,
            'end_time': end_time
        }
        return product.payment_info_timed(**date_info_dict)


class ProductReportParamsSerializer(TimeParamsSerializer):
    """
        start date must be persian format
        times should be +4:30 UTC
    """

    step = serializers.DurationField()

    products = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), many=True)

    @staticmethod
    def validate_step(step):
        if step % datetime.timedelta(days=1) == datetime.timedelta(0):
            return step

        raise serializers.ValidationError(_("step must be a multiple of 24 hours"))

    def validate(self, attrs):
        start_datetime = convert_jalali_to_gregorian(attrs.get('start_date'),
                                                     str(attrs.get('start_time')))
        end_datetime = convert_jalali_to_gregorian(attrs.get('end_date'),
                                                   str(attrs.get('end_time')))

        report_duration = end_datetime - start_datetime

        if attrs.get('step') == datetime.timedelta(days=1) \
                and report_duration > datetime.timedelta(days=14):
            raise serializers.ValidationError(_("Maximum report duration for daily report is 14 days"))

        return attrs


class CafeUserReportSerializer(serializers.ModelSerializer):
    data = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ['pk', 'first_name', 'last_name', 'data', ]

    def get_data(self, instance):
        cafe = self.context.get('cafe')
        return cafe.customer_summary(instance)
