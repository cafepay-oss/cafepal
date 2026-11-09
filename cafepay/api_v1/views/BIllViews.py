from rest_framework.generics import RetrieveUpdateAPIView, RetrieveAPIView

from cafepay.api_v1.serializers.BillSerializers import BillDetailedRetrieveSerializer, BillSimpleRetrieveSerializer
from cafepay.models import Bill
from cafepay.api_v1.permissions import IsStaff, IsStaffOrCustomer


class BillDetailedView(RetrieveAPIView):
    """
        Detailed info of the given bill

        required permissions: is_staff
    """

    permission_classes = (IsStaff,)

    serializer_class = BillDetailedRetrieveSerializer
    queryset = Bill.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'bill_id'


class BillSimpleView(RetrieveAPIView):
    """
        Simple Aggregate information of the bill

        required permission: is_staff or is_participant
    """
    permission_classes = (IsStaffOrCustomer,)

    serializer_class = BillSimpleRetrieveSerializer
    queryset = Bill.objects.all()

    lookup_field = 'pk'
    lookup_url_kwarg = 'bill_id'
