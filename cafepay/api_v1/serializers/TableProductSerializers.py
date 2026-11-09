from django.utils import timezone
from rest_framework import serializers

from cafepay.models import Product, UserProfile


class ProductCountSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    count = serializers.IntegerField(min_value=1)
    user_profile = serializers.PrimaryKeyRelatedField(queryset=UserProfile.objects.all(), required=False)
    is_staff = serializers.BooleanField(required=False)
    pickup_time = serializers.DateTimeField(default=timezone.now)


class TableBulkProductSerializer(serializers.Serializer):
    table_products = ProductCountSerializer(many=True, allow_empty=False)
    description = serializers.CharField(max_length=255, allow_blank=True, required=False)


class TableProductChangesSerializer(serializers.Serializer):
    add = ProductCountSerializer(many=True, required=False, default=list)
    remove = ProductCountSerializer(many=True, required=False, default=list)
    description = serializers.CharField(max_length=255, allow_blank=True, required=False)

    def validate(self, attrs):
        if not attrs['add'] and not attrs['remove']:
            raise serializers.ValidationError('At least one order change is required.')
        return attrs
