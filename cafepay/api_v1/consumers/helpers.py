from django.db.models.query import QuerySet
from django.http.response import Http404
from django.utils.translation import gettext as _


class SocketException(Exception):
    pass


class SafeNotFoundException(SocketException):
    status_code = 404


POST = 'POST'
PUT = 'PUT'
DELETE = 'DELETE'
GET = 'GET'
WATCH = 'WATCH'

MODIFY_METHODS = [POST, PUT, DELETE]
GET_METHODS = [GET, WATCH]

TABLE_SIMPLE_DATA = 'table_simple_data'
TABLE_DETAILED_DATA = 'table_detailed_data'
CAFE_TABLES_SIMPLE_DATA = 'cafe_tables_simple_data'


def get_object_or_404(Base, **kwargs):
    try:
        if type(Base) == QuerySet:
            return Base.get(**kwargs)
        return Base.objects.get(**kwargs)
    except (Base.DoesNotExist, Http404) as e:
        raise ConsumerException(_("Object not found"))


class ConsumerException(SocketException):
    pass
