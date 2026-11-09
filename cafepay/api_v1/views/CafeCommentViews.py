from django.db.models.aggregates import Sum, Count
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from cafepay.api_v1.helpers import clean_null_values
from cafepay.api_v1.permissions import IsLoggedIn
from cafepay.api_v1.serializers.CafeCommentSerializers import ElementSerializer, CafeCommentSerializer
from cafepay.models import RatingElement, Cafe, RatingElementScore


class ElementListView(generics.ListAPIView):
    """
        List of cafe comment elements

        no permissions required
    """
    serializer_class = ElementSerializer
    queryset = RatingElement.objects.all()


class CafeCommentsList(generics.ListAPIView):
    """
        List of verified cafe comments
    """
    serializer_class = CafeCommentSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.comments.filter(verified=True).order_by('-id').distinct()


class CafeCommentCreate(generics.CreateAPIView):
    """
        Create cafe comment

        required permission: isLogedIn
    """

    permission_classes = (IsLoggedIn,)
    serializer_class = CafeCommentSerializer

    def perform_create(self, serializer) -> None:
        serializer.save(user_profile=self.request.user.user_profile)


def get_cafe_el_score(cafe, el):
    ratings = RatingElementScore.objects.filter(el=el, comment__is_valid=True, comment__cafe=cafe)

    agg_data = ratings.aggregate(l=Count('id'), total=Sum('score'))

    clean_null_values(agg_data)

    return agg_data


class CafeElementScore(APIView):
    """
        Aggregate data of a rating element in a cafe

        no permissions required
    """

    def get(self, request, *args, **kwargs):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        el = get_object_or_404(RatingElement, pk=self.kwargs.get('el_id'))

        return Response(get_cafe_el_score(cafe, el))


class CafeAllElementsScore(APIView):
    """
        Aggregate data of a all rating elements in a cafe

        no permissions required
    """

    def get(self, request, *args, **kwargs):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        l = 0
        total = 0

        response = {}
        by_el = []
        for el in RatingElement.objects.all():
            d = get_cafe_el_score(cafe, el)
            l += d['l']
            total += d['total']

            by_el += [{
                'el': {
                    'pk': el.pk,
                    'title': el.title
                },
                'l': d['l'],
                'total': d['total']
            }]

        response['overall'] = {
            'l': l,
            'total': total
        }
        response['by_el'] = by_el

        return Response(response)
