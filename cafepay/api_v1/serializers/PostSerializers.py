from rest_framework import serializers

from cafepay.models import Post, Comment, Like
from cafepay.api_v1.helpers import get_cafe_simple_json, get_cafe_info_serializer, \
    get_user_profile_basic_info_serializer


def simple_user_profile_json(user_profile):
    return {
        'pk': user_profile.pk,
        'username': user_profile.django_user.username,
        'full_name': user_profile.full_name
    }


def simple_user_profile_json_private(user_profile):
    return {
        'pk': user_profile.pk,
        'username': user_profile.django_user.username,
        'full_name': user_profile.full_name,
        'private_id': user_profile.private_id
    }


class PostSerializer(serializers.ModelSerializer):
    # function serializer
    cafe = get_cafe_info_serializer(simple=True)(read_only=True)
    staff = get_user_profile_basic_info_serializer()(read_only=True)

    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ['pk', 'image', 'description', 'cafe', 'is_liked',
                  'staff', 'date', 'type', 'get_type_display',
                  'likes_count']

    def get_is_liked(self, instance):
        if self.context.get('request').user.user_profile:
            return instance.likes.filter(user=self.context.get('request').user.user_profile, post=instance).exists()


class CommentSerializer(serializers.ModelSerializer):
    user = get_user_profile_basic_info_serializer()(read_only=True)

    class Meta:
        model = Comment
        fields = ['pk', 'comment', 'date', 'post', 'user']
        read_only_fields = ['date', 'user', ]


class LikeSerializer(serializers.ModelSerializer):
    user = get_user_profile_basic_info_serializer()(read_only=True)

    class Meta:
        model = Like
        fields = ['pk', 'post', 'user']
        read_only_fields = ['user', 'post']
