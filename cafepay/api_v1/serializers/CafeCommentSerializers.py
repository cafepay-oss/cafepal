from rest_framework import serializers

from cafepay.api_v1.helpers import get_user_profile_basic_info_serializer
from cafepay.models import RatingElement, RatingElementScore, CafeComment


class ElementSerializer(serializers.ModelSerializer):
    class Meta:
        model = RatingElement
        fields = ['pk', 'title']


class RatingElementSerializer(serializers.ModelSerializer):

    element_display = ElementSerializer(read_only=True, source='el')

    class Meta:
        model = RatingElementScore
        fields = ['pk', 'score', 'element_display', 'el']

        extra_kwargs = {
            'el': {'write_only': True}
        }


class CafeCommentSerializer(serializers.ModelSerializer):
    user_profile = get_user_profile_basic_info_serializer()(read_only=True)
    scores = RatingElementSerializer(many=True)

    class Meta:
        model = CafeComment
        fields = ['pk', 'text', 'scores',
                  'cafe', 'verified', 'is_valid',
                  'user_profile', ]

        extra_kwargs = {
            'verified': {'read_only': True},
            'is_valid': {'read_only': True}

        }

    @staticmethod
    def validate_scores(scores):
        exists = {}

        for score in scores:
            if score.get('el').pk in exists.keys():
                raise serializers.ValidationError("Duplicate key detected")
            exists[score.get('el').pk] = True

        return scores

    def create(self, validate_data):

        # invalidate all other comments of this user on this cafe
        comments = CafeComment.objects.filter(cafe=validate_data.get('cafe'),
                                              user_profile=validate_data.get('user_profile'))

        comments.update(is_valid=False)

        # create the new comment
        scores = validate_data.pop('scores')

        cafe_comment = CafeComment.objects.create(**validate_data)

        for score in scores:
            RatingElementScore.objects.create(comment=cafe_comment, **score)

        return cafe_comment

