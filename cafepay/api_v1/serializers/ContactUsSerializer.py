from rest_framework import serializers

from cafepay.models import ContactUsForm


class ContactUsCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactUsForm
        fields = ['pk', 'full_name', 'phone_number', 'biz_name', 'address', 'text']
