from rest_framework import serializers

from cafepay.models import CharacterField


class CafeCharFieldSerializer(serializers.ModelSerializer):

    class Meta:
        model = CharacterField
        fields = ['pk', 'cafe', 'title',
                  'is_delete', 'menu',
                  'description', 'type', 'get_type_display']

        extra_kwargs = {
            'cafe': {'read_only': True},
            'get_type_display': {'read_only': True},
        }

