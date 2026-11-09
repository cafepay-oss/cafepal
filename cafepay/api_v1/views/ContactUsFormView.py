from rest_framework import generics

from cafepay.api_v1.serializers.ContactUsSerializer import ContactUsCreateSerializer


class ContactUsCreateView(generics.CreateAPIView):
    """
    Contact us
    """
    serializer_class = ContactUsCreateSerializer

