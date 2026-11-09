from typing import List

from .ConsumerView import path
from .consumer_views import TableProductManageByToken, TableProductManageByPk, TableSimpleJoinByPkView, \
    TableSimpleJoinView, TableAggregateData, CafeTablePrintersJob, TableStatusView, TableSimpleJoinByUUIDView

paths = [
    path('table/<table_token>/product/<product_id>/',
         TableProductManageByToken.as_view(), name="table-add/remove-product-by-token"),

    path('table/<table_id>/product/<product_id>/staff/',
         TableProductManageByPk.as_view(), name="table-add/remove-product-by-pk"),

    path('table/<table_token>/join/simple/by-token/',
         TableSimpleJoinView.as_view(), name="table-join-simple-by-token"),

    path('table/<table_id>/join/simple/by-id/',
         TableSimpleJoinByPkView.as_view(), name="table-join-simple-by-id"),

    path('table/<table_uuid>/join/simple/by-uuid/',
         TableSimpleJoinByUUIDView.as_view(), name="table-join-simple-by-uuid"),

    path('table/<table_id>/aggregate/',
         TableAggregateData.as_view(), name="table-aggregate"),

    path('cafe/<cafe_id>/printer/jobs/',
         CafeTablePrintersJob.as_view(), name="cafe-printer-jobs", ),

    path('cafe/<cafe_id>/tables/join/simple/<type>/',
         TableStatusView.as_view(), name="cafe-join-simple", )
]

