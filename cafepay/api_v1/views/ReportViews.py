import datetime

from django.core.validators import RegexValidator
from django.db.models import Count
from django.db.models.aggregates import Sum
from django.urls import resolve
from rest_framework.generics import ListAPIView, get_object_or_404
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from django.utils.translation import gettext as _

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import convert_jalali_to_gregorian, AggregatedListAPIView, SumDistinctHACK, \
    ManagerialReport, super_advanced_datetime_filter, get_payment_info
from cafepay.api_v1.permissions import IsStaff
from cafepay.api_v1.serializers.ReportSerializers import ProductReportParamsSerializer, \
    CafeUserReportSerializer
from cafepay.api_v1.serializers.TableSerializers import DummySerializer
from cafepay.api_v1.serializers.UserProfileSerializrs import UserProfileUpdateSerializer
from cafepay.models import Product, Cafe, UserProfile, Invoice, TableJoin, ProductBillRelation
from django_filters import rest_framework as filters


class ProductsReportsFilterSet(filters.FilterSet):
    start_date = filters.CharFilter(label="start_date", required=True, validators=[
        RegexValidator(
            r'^[1][1-4][0-9]{2}\/((0[1-6]\/(0[1-9]|[1-2][0-9]|3[0-1]))|(0[7-9]\/(0[1-9]|[1-2][0-9]|30))|('
            r'1[0-1]\/(0[1-9]|[1-2][0-9]|30))|(12\/(0[1-9]|[1-2][0-9])))'),
    ])

    end_date = filters.CharFilter(label="end_date", required=True, validators=[
        RegexValidator(
            r'^[1][1-4][0-9]{2}\/((0[1-6]\/(0[1-9]|[1-2][0-9]|3[0-1]))|(0[7-9]\/(0[1-9]|[1-2][0-9]|30))|('
            r'1[0-1]\/(0[1-9]|[1-2][0-9]|30))|(12\/(0[1-9]|[1-2][0-9])))'),
    ])
    start_time = filters.TimeFilter(label="start_time", required=True)
    end_time = filters.TimeFilter(label="end_time", required=True)


class ProductReportFilterBackend(filters.DjangoFilterBackend):
    """
    only used to validate filter params
    """
    def filter_queryset(self, request, queryset, view):
        return queryset


class GetProductReports(ListAPIView):
    permission_classes = (IsStaff, )
    filter_backends = [ProductReportFilterBackend, ]
    filterset_class = ProductsReportsFilterSet

    serializer_class = DummySerializer

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.params_validated = False
        self.filterset = 0

    def get_queryset(self):
        return ProductBillRelation.objects.filter(bill__table__cafe__pk=self.kwargs.get('cafe_id'))

    def validate_filter_params(self):
        # calling the filter queryset, automatically validates the filter params
        self.filter_queryset(self.get_queryset())
        self.params_validated = True

    def get_filter_params(self):
        if not self.params_validated:
            raise Exception(_("Filter params should be validated before getting the params"))
        return self.parse_str_params(*self.extract_params_from_kwargs())

    def extract_params_from_kwargs(self):
        start_date = self.request.query_params.get('start_date')
        start_time = self.request.query_params.get('start_time')
        end_date = self.request.query_params.get('end_date')
        end_time = self.request.query_params.get('end_time')
        return start_date, start_time, end_date, end_time

    @staticmethod
    def parse_str_params(end_date, end_time, start_date, start_time):
        start = convert_jalali_to_gregorian(date=start_date.replace('/', '-'),
                                            _time=start_time)
        end = convert_jalali_to_gregorian(date=end_date.replace('/', '-'),
                                          _time=end_time)
        start_time = start.time()
        start_date = start.date()
        end_time = (end + datetime.timedelta(seconds=59, microseconds=999999)).time()
        end_date = end.date()
        return end_date, end_time, start_date, start_time

    def filter_the_queryset(self):
        return super_advanced_datetime_filter(self.get_queryset(), "datetime", *self.get_filter_params())

    def get_products(self):
        return Product.objects.filter(cafe__pk=self.kwargs.get('cafe_id'))

    def get(self, request, *args, **kwargs):
        self.validate_filter_params()
        products = self.get_products()
        product_bill_relations = self.filter_the_queryset()

        reports = self.generate_reports(product_bill_relations, products)

        return Response(reports)

    def generate_reports(self, product_bill_relations, products):
        reports = []
        for product in products:
            self.get_product_report(product, product_bill_relations, reports)
        return reports

    @staticmethod
    def get_product_report(product, product_bill_relations, reports):
        product_pbrs = product_bill_relations.filter(product=product)
        payment_info = get_payment_info(product_pbrs)
        reports.append({
            'product': product.pk,
            'payment_info': payment_info
        })


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


class CafeUserFilterSet(filters.FilterSet):
    amount = filters.NumberFilter(label='amount', method='filter_total_amount')
    amount__gte = filters.NumberFilter(label='amount__gte', method='filter_total_amount')
    amount__lte = filters.NumberFilter(label='amount__lte', method='filter_total_amount')
    amount__gt = filters.NumberFilter(label='amount__gt', method='filter_total_amount')
    amount__lt = filters.NumberFilter(label='amount__lt', method='filter_total_amount')

    total_retention = filters.NumberFilter(label="total_retention", method='filter_total_retention')
    total_retention__gte = filters.NumberFilter(label="total_retention__gte", method='filter_total_retention')
    total_retention__lte = filters.NumberFilter(label="total_retention__lte", method='filter_total_retention')
    total_retention__gt = filters.NumberFilter(label="total_retention__gt", method='filter_total_retention')
    total_retention__lt = filters.NumberFilter(label="total_retention__lt", method='filter_total_retention')

    """
    total amount spent: total amount of all pbrs
    total retention
    
    """

    def get_cafe(self):
        request_url = self.request.path
        resolved = resolve(request_url)

        cafe_id = resolved.kwargs.get('cafe_id')
        cafe = get_object_or_404(Cafe, pk=cafe_id)

        return cafe

    # todo: filter average spent

    def filter_total_retention(self, queryset, name, value):
        cafe = self.get_cafe()

        # calculate total retention of each user
        # retention defined as: total number of joins a users has created

        # calculate all users retentions
        total_times_ordered = TableJoin.objects.filter(
            bills__bill_pbrs__product__in=cafe.products.all(),
            bills__bill_pbrs__user_profile__in=queryset
        ).distinct(). \
            values('bills__bill_pbrs__user_profile'). \
            annotate(total_retention=Count('pk', distinct=True))

        # filter the intended retention
        total_times_ordered = total_times_ordered. \
            filter(**{name: value}). \
            values('bills__bill_pbrs__user_profile')

        return queryset.filter(private_id__in=total_times_ordered)

    def filter_total_amount(self, queryset, name, value):
        cafe = self.get_cafe()

        # total users spent: aggregate count of all withdraw invoices of the a user in a specific cafe
        users_spent = Invoice.objects.filter(wallet__user_profile__in=queryset,
                                             type=InvoiceConsts.WITHDRAW,
                                             pbr__product__in=cafe.products.all()) \
            .distinct(). \
            values('wallet__user_profile'). \
            annotate(total_amount=SumDistinctHACK('amount'))

        # filter the intended user spent
        users_spent = users_spent. \
            filter(**{name: value}). \
            values('wallet__user_profile')
        data = cafe.customers.filter(pk__in=users_spent)

        return data


class CafeUsersReportsView(AggregatedListAPIView):
    """
    Cafe Users List and their financial summary

    sample response

        {
            "count": 10,
            "next": null,
            "previous": null,
            "total_amount": 436500,
            "total_times_ordered": 55,
            "average_spent": 7937,
            "fav_product": "ماست موسیر رامک 250 گرم"
            "results": [
                {
                    "pk": 20,
                    "first_name": "شیرین",
                    "last_name": "محبی",
                    "data": {
                        "total_amount": 0,
                        "total_times_ordered": 6,
                        "average_spent": 0,
                        "fav_product": "شکلات صبحانه تلخ فندقی فرمند 200 گرم"
                    }
                },
            ]
        }

    """

    serializer_class = CafeUserReportSerializer
    pagination_class = StandardResultsSetPagination

    filter_backends = [filters.DjangoFilterBackend, SearchFilter]
    filterset_class = CafeUserFilterSet
    search_fields = ['first_name', 'last_name']

    def get_serializer_context(self):
        context = {
            'request': self.request,
            'view': self,
        }

        if self.kwargs.get('cafe_id'):
            context['cafe'] = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        else:
            context['cafe'] = None

        return context

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.customers

    def get_aggregated_data(self, queryset):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.customer_summary(queryset, many=True)


class NewCustomersReports(ManagerialReport):
    """
     new cafe customers:

     customers that their first join in a cafe is created in the given time frame
    """

    serializer_class = UserProfileUpdateSerializer
    queryset = Cafe.objects.all()
    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_id'

    def get_total_queryset_items(self):
        cafe = self.get_object()
        return cafe.customers.count()

    def get_framed_queryset(self, start_datetime, end_datetime):
        """Queryset that satisfies the given time constraints"""

        cafe = self.get_object()

        # table joins in the given time frame
        framed_joins = TableJoin.objects.filter(datetime__gte=start_datetime, datetime__lte=end_datetime, cafe=cafe)

        # group table joins by pbr user_profile s
        framed_customers = framed_joins.values("bills__bill_pbrs__user_profile").distinct()
        all_customers = UserProfile.objects.filter(private_id__in=framed_customers)

        # filter user profiles that don't have any other joins in this cafe
        # this makes them new customer in the given time frame
        old_customers = UserProfile.objects.filter(orders__bill__join__cafe=cafe,
                                                   private_id__in=framed_customers,
                                                   orders__bill__join__datetime__lte=start_datetime,
                                                   orders__bill__join__datetime__gte=end_datetime)

        new_customers = all_customers.difference(old_customers).count()

        return new_customers


class OrderReports(ManagerialReport):
    """
     cafe orders

    """

    serializer_class = UserProfileUpdateSerializer
    queryset = Cafe.objects.all()
    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_id'

    def get_total_queryset_items(self):
        cafe = self.get_object()
        return cafe.joins.all().count()

    def get_framed_queryset(self, start_datetime, end_datetime):
        cafe = self.get_object()

        # table joins in the given time frame
        framed_joins = TableJoin.objects.filter(datetime__gte=start_datetime, datetime__lte=end_datetime, cafe=cafe)
        return framed_joins.count()


class SalesReports(ManagerialReport):
    """
     cafe sales

    """

    serializer_class = UserProfileUpdateSerializer
    queryset = Cafe.objects.all()
    lookup_field = 'pk'
    lookup_url_kwarg = 'cafe_id'

    def get_total_queryset_items(self):
        cafe = self.get_object()
        all_income = cafe.wallet.total_income_invoices
        total_income = all_income.aggregate(income=Sum('amount'))

        if total_income.get('income'):
            return total_income.get('income')

        return 0

    def get_framed_queryset(self, start_datetime, end_datetime):
        cafe = self.get_object()
        wallet = cafe.wallet
        income_invoices = wallet.total_income_invoices

        framed_invoiecs = income_invoices.filter(create_datetime__gte=start_datetime, create_datetime__lte=end_datetime)

        total_amount = framed_invoiecs.aggregate(income=Sum('amount'))

        if total_amount.get('income'):
            return total_amount.get('income')

        return 0
