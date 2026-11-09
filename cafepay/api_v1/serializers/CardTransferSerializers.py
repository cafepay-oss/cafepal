import re
from django.urls import reverse
from rest_framework import serializers
from cafepay.models import Cafe, CardTransfer


class CardTransferSettingsSerializer(serializers.ModelSerializer):
    card_transfer_number = serializers.CharField(max_length=32, allow_blank=True, required=False)
    class Meta:
        model = Cafe
        fields = ['card_transfer_enabled', 'card_transfer_number', 'card_transfer_holder']

    def validate_card_transfer_number(self, value):
        value = value.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
        value = re.sub(r'[\s-]', '', value)
        if value and not re.fullmatch(r'[0-9]{16}', value):
            raise serializers.ValidationError('شماره کارت باید ۱۶ رقم باشد.')
        return value

    def validate(self, attrs):
        enabled = attrs.get('card_transfer_enabled', self.instance.card_transfer_enabled)
        if enabled and (not attrs.get('card_transfer_number', self.instance.card_transfer_number) or
                        not attrs.get('card_transfer_holder', self.instance.card_transfer_holder).strip()):
            raise serializers.ValidationError('شماره کارت و نام صاحب کارت را وارد کنید.')
        return attrs


class CardTransferSerializer(serializers.ModelSerializer):
    receipt_url = serializers.SerializerMethodField()
    table_uuid = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)

    class Meta:
        model = CardTransfer
        fields = ['uuid', 'join', 'cafe', 'status', 'amount', 'delivery_fee',
                  'destination_card', 'destination_holder', 'receipt_url',
                  'created_at', 'submitted_at', 'reviewed_at', 'review_note',
                  'customer_name', 'table_uuid']
        read_only_fields = fields

    def get_receipt_url(self, instance):
        return reverse('card_transfer_receipt', kwargs={'transfer_uuid': instance.uuid}) if instance.receipt else None

    def get_table_uuid(self, instance):
        bill = instance.join.bills.select_related('table').order_by('pk').first()
        return str(bill.table.uuid) if bill and bill.table.uuid else None


class CardTransferReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=['confirm', 'reject'])
    note = serializers.CharField(max_length=500, required=False, default='', allow_blank=True)

    def validate(self, attrs):
        if attrs['decision'] == 'reject' and not attrs['note'].strip():
            raise serializers.ValidationError('دلیل رد رسید را برای مشتری بنویسید.')
        return attrs
