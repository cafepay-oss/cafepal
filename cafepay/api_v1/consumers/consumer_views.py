from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _
from rest_framework import status

from .ConsumerView import BaseConsumerView, Path, ConsumerRetrieveAPIView, ConsumerListAPIView
from .ConsumerView import ConsumerResponse as Response
from .ConsumerView import MethodPathEffect as _Af
from .helpers import get_object_or_404
from ..helpers import get_table_by_token, APIBadRequest
from ..permissions import IsLoggedIn, IsStaff
from ..serializers.CafePrinterSerializer import PrintRawDataSerializer, CafePrinterJobsSerializer
from ..serializers.JoinSerializers import JoinSimpleSerializer, JoinAggregateSerializer
from ..serializers.TableSerializers import TableCRUDSerializer
from ...models import Product, Table, TableToken, Cafe, TableJoin


class TableProductManageByToken(BaseConsumerView):
    """
        add/remove product by table token

        POST to add product to table
        DELETE to remove product from table

        an active table token is required

        actions are done to the active bill of the table
    """

    permission_classes = (IsLoggedIn,)

    def get_table(self):
        return get_table_by_token(token=self.kwargs.get('table_token'),
                                  user_profile=self.request.user.user_profile)

    def get_affected_method_paths(self):
        table_id = self.get_table().pk
        return [
            _Af(Path.reverse(name="table-join-simple-by-token",
                             kwargs={'table_token': self.kwargs.get('table_token')})),
            _Af(Path.reverse(name="table-join-simple-by-id",
                             kwargs={'table_id': table_id})),
            _Af(Path.reverse(name="table-aggregate",
                             kwargs={'table_id': table_id})),
        ]

    async def post(self, request, *args, **kwargs):
        """
            Add product to table
        """
        with transaction.atomic():
            table = self.get_table()

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.add_product(product, request.user.user_profile)

            return Response()

    async def delete(self, request, *args, **kwargs):
        with transaction.atomic():
            table = self.get_table()

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.remove_product(product, request.user.user_profile)

            return Response(status=status.HTTP_204_NO_CONTENT)


class TableProductManageByPk(BaseConsumerView):
    """
        add/remove product by table pk

        POST to add product to table
        DELETE to remove product from table

        actions are done to the active bill of the table

        required permission: is_staff
    """

    permission_classes = (IsStaff,)

    def get_affected_method_paths(self):
        # todo: handle token not found exception
        filters = {
            'table__id': self.kwargs.get('table_id'),
            'status': TableToken.ACTIVE
        }
        if not TableToken.objects.filter().exists():
            return []

        token = TableToken.objects.get(**filters)

        # refactor artifact todo: clean up
        token = {
            'token': token.token
        }

        return [
            _Af(Path.reverse(name="table-join-simple-by-token",
                             kwargs={'table_token': token['token']})),
            _Af(Path.reverse(name="table-join-simple-by-id",
                             kwargs={'table_id': self.kwargs.get('table_id')})),
            _Af(Path.reverse(name="table-aggregate",
                             kwargs={'table_id': self.kwargs.get('table_id')}))
        ]

    @staticmethod
    async def post(request, *args, **kwargs):
        """
            Add product to table
        """
        with transaction.atomic():
            table = get_object_or_404(Table, pk=kwargs.get('table_id'))

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.add_product(product, request.user.user_profile, is_staff=True)

            return Response()

    @staticmethod
    async def delete(request, *args, **kwargs):
        with transaction.atomic():
            table = get_object_or_404(Table, pk=kwargs.get('table_id'))

            product = get_object_or_404(Product, pk=kwargs.get('product_id'))

            table.remove_product(product, request.user.user_profile, True)

            return Response(status=status.HTTP_204_NO_CONTENT)


class TableSimpleJoinByPkView(ConsumerRetrieveAPIView):
    """
        simple join info of the given table

        required permission: IsStaff
    """
    permission_classes = (IsLoggedIn,)
    serializer_class = JoinSimpleSerializer

    def get_object(self):
        table = get_object_or_404(Table, pk=self.kwargs.get('table_id'))
        active_join = table.active_join
        if not active_join:
            raise APIBadRequest(detail=_("No active join"), status_code=status.HTTP_404_NOT_FOUND)
        return active_join


class TableSimpleJoinByUUIDView(ConsumerRetrieveAPIView):
    """
        simple join info of the given table

    """
    permission_classes = (IsLoggedIn,)
    serializer_class = JoinSimpleSerializer

    def get_object(self):
        table = get_object_or_404(Table, uuid=self.kwargs.get('table_uuid'))
        active_join = table.active_join
        if not active_join:
            raise APIBadRequest(detail=_("No active join"), status_code=status.HTTP_404_NOT_FOUND)
        return active_join


class TableSimpleJoinView(ConsumerRetrieveAPIView):
    """
        simple join info of the given table

        an active table token is required

        required permission: is_logged_in
    """
    permission_classes = (IsLoggedIn,)
    serializer_class = JoinSimpleSerializer

    def get_serializer_context(self):
        return {
            'request': self.request,
            'view': self,
            'has_my_payments': True,
            'only_my_pbr': True
        }

    def get_object(self):

        # token and uuid is accepted
        try:
            table = TableToken.objects.get(token=self.kwargs.get('table_token'),
                                           status=TableToken.ACTIVE).table
        except TableToken.DoesNotExist:
            table = get_object_or_404(Table, uuid=self.kwargs.get('table_token'))

        active_join = table.active_join
        if not active_join:
            raise APIBadRequest(detail=_("No active join"), status_code=status.HTTP_404_NOT_FOUND)
        return active_join


class TableAggregateData(ConsumerRetrieveAPIView):
    """
        Aggregate info on a table

        required permission: IsStaff
    """
    permission_classes = (IsStaff,)
    serializer_class = JoinAggregateSerializer

    def get_object(self):
        table = get_object_or_404(Table, pk=self.kwargs.get('table_id'))
        active_join = table.active_join
        if not active_join:
            raise APIBadRequest(detail=_("No active join"), status_code=status.HTTP_404_NOT_FOUND)
        return active_join


class CafeTablePrintersJob(ConsumerListAPIView):
    """All cafe printers active jobs"""

    permission_classes = (IsStaff,)
    serializer_class = CafePrinterJobsSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.printers.all()


class TableStatusView(ConsumerListAPIView):
    """
        join simple view of all the tables of the cafe

        required permissions: is_staff
    """

    permission_classes = (IsStaff,)
    serializer_class = JoinSimpleSerializer

    def get_queryset(self):
        table_type = self.kwargs.get('type', TableToken.SELF_PICKUP)
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))

        table_joins = cafe.joins.filter(~Q(bills__bill_pbrs=None),
                                        sent=False,
                                        force_close=False)
        if table_type != "any":
            return table_joins.filter(bills__table__table_type=table_type)

        return table_joins
