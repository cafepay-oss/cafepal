import asyncio
import calendar
import datetime
import json
import logging
import random

import jdatetime
import pytz
import requests
from asgiref.sync import async_to_sync
from django.db.models import F, Count
from django.db.models.aggregates import Sum
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext as _
from drf_yasg import openapi
from furl import furl
from persiantools.jdatetime import JalaliDateTime
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from cafepal import settings
from cafepal.secret import DEMO
from sms.models import Operator, Message
from pydoc import locate

from django.db.models import Sum


class SumDistinctHACK(Sum):
    allow_distinct = True


def locate_from_api_v1_serializers(path):
    _from = "%s.%s" % ("cafepay.api_v1.serializers",
                       path)
    c = locate(_from)
    return c


def generate_code():
    return str(random.randint(10000, 99999))


def generate_table_token():
    return str(random.randint(100000000000, 999999999999))


def get_verification_text(code):
    return _("به کافه پی خوش آمدید: %s" % code)


def send_verification_code(to, code):
    message = Message.objects.create(to=to, message=str(code))

    if DEMO:
        # Don't send actual sms if running on debug mode
        return

    return Operator.objects.get(vendor=Operator.KAVENEGAR).send_message(message)


def get_cafe_simple_json(cafe):
    return {'pk': cafe.pk, 'name': cafe.name}


class OverallRatingField(serializers.JSONField):
    class Meta:
        swagger_schema_fields = {
            "type": openapi.TYPE_OBJECT,
            "title": "Overall Rating Field",
            "properties": {
                "rate": openapi.Schema(
                    title="Overall rating",
                    type=openapi.FORMAT_FLOAT,
                ),
                "count": openapi.Schema(
                    title="Count",
                    type=openapi.TYPE_INTEGER,
                ),
            },
        }


class PaymentInfoField(serializers.JSONField):
    class Meta:
        swagger_schema_fields = {
            "type": openapi.TYPE_OBJECT,
            "title": "Payment Info field",
            "properties": {
                "total_count": openapi.Schema(
                    title="Total count",
                    type=openapi.FORMAT_FLOAT,
                ),
                "total_amount": openapi.Schema(
                    title="Total amount",
                    type=openapi.FORMAT_FLOAT,
                ),
                "payed_amount": openapi.Schema(
                    title="Payed Amount",
                    type=openapi.TYPE_INTEGER,
                ),
                "refund_amount": openapi.Schema(
                    title="Refund Amount",
                    type=openapi.TYPE_INTEGER,
                ),
                "net_amount": openapi.Schema(
                    title="Net Amount",
                    type=openapi.TYPE_INTEGER,
                ),
            },
        }


# small helper serializer


def get_payment_info(pbrs, only_invoices=False):
    """
        :param pbrs: array of product bill relation objects to calculate payment info
        :return: aggregated payment info
    """

    if not pbrs:
        return {
            'total_count': 0,
            'total_amount': 0,
            'payed_amount_pos': 0,
            'payed_amount_cash': 0,
            'payed_amount_online': 0,
            'refund_amount': 0,
            'net_payed_amount': 0,
            'net_amount': 0,
        }

    from cafepay.api_v1.consts import InvoiceConsts
    from cafepay.models import Invoice

    total_count = pbrs.aggregate(total_count=Sum('count'))

    total_amount = pbrs.aggregate(total_amount=Sum(F('count') * F('original_price') * (100 - F('discount')) / 100))

    payed_invoices = Invoice.objects.filter(tag=InvoiceConsts.PAYED_FOR_PRODUCT,
                                            type=InvoiceConsts.DEPOSIT,
                                            status__in=[InvoiceConsts.INTERNAL, InvoiceConsts.PAYED],
                                            pbr__in=pbrs)
    payed_invoices_pos = payed_invoices.filter(method=InvoiceConsts.POS)
    payed_invoices_cash = payed_invoices.filter(method=InvoiceConsts.CASH)
    payed_invoices_online = payed_invoices.filter(method=InvoiceConsts.ONLINE)

    agg_payed = payed_invoices.aggregate(payed_amount=Sum('amount'))
    agg_payed_pos = payed_invoices_pos.aggregate(payed_amount=Sum('amount'))
    agg_payed_cash = payed_invoices_cash.aggregate(payed_amount=Sum('amount'))
    agg_payed_online = payed_invoices_online.aggregate(payed_amount=Sum('amount'))

    refund_invoices = Invoice.objects.filter(tag=InvoiceConsts.REFUND,
                                             type=InvoiceConsts.WITHDRAW,
                                             pbr__in=pbrs)

    agg_refund = refund_invoices.aggregate(refund_amount=Sum('amount'))

    if only_invoices:
        return {
            'payed_invoices': payed_invoices,
            'refund_invoices': refund_invoices
        }

    clean_null_values(agg_payed)
    clean_null_values(agg_payed_pos)
    clean_null_values(agg_payed_cash)
    clean_null_values(agg_payed_online)
    clean_null_values(agg_refund)
    clean_null_values(total_amount)
    clean_null_values(total_count)

    total_amount = total_amount['total_amount']

    return {
        'total_count': total_count['total_count'],
        'total_amount': total_amount,

        'payed_amount': agg_payed['payed_amount'],
        'payed_amount_pos': agg_payed_pos['payed_amount'],
        'payed_amount_cash': agg_payed_cash['payed_amount'],
        'payed_amount_online': agg_payed_online['payed_amount'],

        'refund_amount': agg_refund['refund_amount'],
        'net_payed_amount': agg_payed['payed_amount'] -
                            agg_refund['refund_amount'],
        'net_amount': (total_amount -
                       agg_payed['payed_amount'] +
                       agg_refund['refund_amount'])
    }


def get_user_profile_basic_info_serializer(phone=False):
    from cafepay.models import UserProfile

    class Serializer(serializers.ModelSerializer):
        class Meta:
            model = UserProfile
            fields = ['pk', 'full_name', 'email', 'first_name',
                      'last_name', 'phone_number']

    class SerializerPhone(serializers.ModelSerializer):
        class Meta:
            model = UserProfile
            fields = ['pk', 'full_name', 'email', 'phone_number', 'first_name',
                      'last_name', ]

    if not phone:
        return Serializer

    return SerializerPhone


def get_cafe_info_serializer(simple=False):
    from cafepay.models import Cafe
    from cafepay.api_v1.serializers.AddressSerializers import CafeRegionDetailedSerializer

    class Serializer(serializers.ModelSerializer):
        if not simple:
            overall_rating = OverallRatingField(read_only=True)
            delivery_regions = CafeRegionDetailedSerializer(many=True)

        avatar = serializers.ImageField()

        class Meta:
            model = Cafe

            if not simple:
                fields = ['pk', 'overall_rating',
                          'has_delivery',
                          'delivery_regions',
                          'name', 'is_open', 'payment_only',
                          'avatar', 'payment_first', 'card_transfer_enabled',
                          'phone',
                          'cafepay_fee']
            else:
                fields = ['pk', 'name', 'cafepay_fee', 'avatar',
                          'phone', 'has_delivery',
                          'payment_first', 'payment_only', 'card_transfer_enabled']

    return Serializer


def get_basic_menu_serializer():
    from cafepay.models import Menu

    class Serializer(serializers.ModelSerializer):
        class Meta:
            model = Menu
            fields = ['pk', 'name', 'staff', 'is_active']

    return Serializer


def get_product_basic_info_serializer():
    from cafepay.models import Product

    class _Serializer(serializers.ModelSerializer):
        class Meta:
            model = Product
            fields = ['pk', 'name', 'order']

            ref_name = "pbis"

    return _Serializer


def get_basic_char_field_serializer():
    from cafepay.models import CharacterField

    class Serializer(serializers.ModelSerializer):
        class Meta:
            model = CharacterField
            fields = ['pk', 'title', 'cafe',
                      'is_delete', 'menu',
                      'staff', 'type']

    return Serializer


def get_table_simple_serializer():
    from cafepay.models import Table

    class Serializer(serializers.ModelSerializer):
        class Meta:
            model = Table
            fields = ['pk', 'number', 'is_preorder']

    return Serializer


def get_table_by_token(token, user_profile):
    from cafepay.models import TableToken
    table = get_object_or_404(TableToken, token=token, status=TableToken.ACTIVE).table

    return table


class APIBadRequest(APIException):
    status_code = 400

    def __init__(self, *args, **kwargs):
        self.status_code = kwargs.pop('status_code', 400)
        super(APIBadRequest, self).__init__(*args, **kwargs)


JOIN = '0'
TRANSFER = '2'


def validate_table_operation(t1, t2, op):
    if t1 == t2:
        raise APIBadRequest(detail=_("Same table operations not valid"))

    if t1.cafe != t2.cafe:
        raise APIBadRequest(detail=_("Cafe mismatch"))

    if not t1.active_join and not t2.active_join:
        raise APIBadRequest(detail=_("Empty tables operation not valid"))

    if op == TRANSFER:
        if not t1.active_join:
            raise APIBadRequest(detail=_("Cannot transfer empty table"))


def clean_null_values(aggregated_queryset):
    for key in aggregated_queryset.keys():
        if aggregated_queryset[key] is None:
            aggregated_queryset[key] = 0


def _thread_notifier(table):
    from cafepay.api_v1.consumers.DispatchConsumer import DispatchConsumer
    from cafepay.models import TableToken

    # todo: send to all joins
    # ----------------- socket notifications
    notify_watcher = async_to_sync(DispatchConsumer.notify_watcher_endpoint)
    _table_token = table.table_tokens.filter(status=TableToken.ACTIVE).first()
    _table_uuid = table.uuid

    notify_watcher(
        'table/%d/join/simple/by-id/' % table.pk
    )

    notify_watcher(
        'table/%d/aggregate/' % table.pk
    )

    notify_watcher(
        'cafe/%d/tables/join/simple/%s/' % (table.cafe.pk, TableToken.SELF_PICKUP)
    )

    notify_watcher(
        'cafe/%d/tables/join/simple/%s/' % (table.cafe.pk, TableToken.PAYMENT_ONLY)
    )

    notify_watcher(
        'cafe/%d/tables/join/simple/any/' % table.cafe.pk
    )

    if _table_token:
        notify_watcher(
            'table/%s/join/simple/by-token/' % _table_token.token)

    if _table_uuid:
        notify_watcher(
            'table/%s/join/simple/by-token/' % _table_uuid)


def _desktop_notification_thread(table):
    from django.conf import settings
    if getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False):
        return
    if table.is_preorder:
        cafe = table.cafe
        push_endpoints = cafe.push_endpoints.all()
        push_requests = []
        payload = {
            'title': 'پیش سفارش | کافه پی',
            'body': 'پیش سفارش جدید برای شما ثبت شده است',
            'url': 'https://admin.cafepay.app'
        }
        payload_text = json.dumps(payload)

        for push_endpoint in push_endpoints:
            push_requests.append({
                'text': payload_text,
                'keys': push_endpoint.keys,
                'subscription': push_endpoint.text
            })

        data = {
            'data': push_requests
        }

        url = getattr(settings, 'PUSH_SERVICE_URL', '')
        token = getattr(settings, 'PUSH_SERVICE_TOKEN', '')
        if not url or not token or not push_requests:
            return False
        try:
            response = requests.post(url, json=data,
                                     headers={'Authorization': 'Bearer ' + token},
                                     timeout=(3.05, 5), verify=True)
            response.raise_for_status()
            return True
        except requests.RequestException:
            # Do not log subscription keys, tokens, request bodies, or response bodies.
            logging.getLogger(__name__).warning('Push service request failed')
            return False


def _printer_thread_notifier(printer):
    from cafepay.api_v1.consumers.DispatchConsumer import DispatchConsumer

    notify_watcher = async_to_sync(DispatchConsumer.notify_watcher_endpoint)

    notify_watcher(
        'cafe/%d/printer/jobs/' % printer.cafe.pk
    )


def notify_watchers(table):
    import threading

    thread1 = threading.Thread(target=_thread_notifier, args=(table,))
    thread1.start()


def notify_printers(printer):
    import threading

    thread1 = threading.Thread(target=_printer_thread_notifier, args=(printer,))
    thread1.start()


def convert_jalali_to_gregorian(date, _time):
    """
    :param date: date - either str or date object (str objects must be validated before passing to this function)
    :param _time: time - either str or time object (str objects must be validated before passing to this function)
    :return: converted and merged datetime object
    """

    if type(date) == str:
        date_data = date.split('-')
    else:
        date_data = str(date).split('-')

    if type(_time) == str:
        time_data = _time.split(':')
    else:
        time_data = str(_time).split(':')

    datetime_data = date_data + time_data
    datetime_data = [int(dt) for dt in datetime_data]

    nytz = pytz.timezone('Asia/Tehran')

    return datetime.datetime.fromtimestamp(
        calendar.timegm(nytz.localize(jdatetime.datetime(*datetime_data).togregorian()).utctimetuple()),
        tz=pytz.timezone("utc"))


def super_advanced_datetime_filter(queryset, datetime_field,
                                   start_date, start_time,
                                   end_date, end_time):
    """
    :param queryset:
    :param datetime_field:
    :param start_date:
    :param start_time:
    :param end_date:
    :param end_time:
    :return: filter a queryset across a date and time frame
    """

    # Scenario 1: start time < end time, perform a regular datetime filter
    if start_time <= end_time:
        return queryset.filter(**{
            "%s__date__gte" % datetime_field: start_date,
            "%s__date__lte" % datetime_field: end_date,
            "%s__time__gte" % datetime_field: start_time,
            "%s__time__lte" % datetime_field: end_time,
        })
    elif end_time < start_time:
        """
        converted time is like: from 01:00 until 11:00 
        
        q1: 
        ***********************************
        *  ----  ----  ----  ----  ----  *  00:00
        *  |  |  |  |  |  |  |  |  |  |  *
        *  |  |  |  |  |  |  |  |  |  |  *
        *  ----  ----  ----  ----  ----  *  21:30
        ***********************************
        
        q2:
                **********************************
                *  ----  ----  ----  ----  ----  *  07:30
                *  |  |  |  |  |  |  |  |  |  |  *
                *  |  |  |  |  |  |  |  |  |  |  *
                *  ----  ----  ----  ----  ----  *  00:00
                **********************************
        """
        q1 = queryset.filter(**{
            "%s__date__gte" % datetime_field: start_date,
            "%s__date__lt" % datetime_field: end_date,
            "%s__time__gte" % datetime_field: start_time
        })

        q2 = queryset.filter(**{
            "%s__date__gt" % datetime_field: start_date,
            "%s__date__lte" % datetime_field: end_date,
            "%s__time__lte" % datetime_field: end_time
        })

        return (q1 | q2).distinct()
    else:
        raise Exception("[ERROR] CPU Malfunction")


class AggregatedListAPIView(ListAPIView):
    """
    ListAPIView with aggregated data on the filtered queryset
    also supports total queryset aggregation when pagination is used
    """

    def get_extra_and_paginated_response(self, page, extra):
        """
        :param page: page of data
        :param extra: a dictionary containing extra fields to be included in the final response
        :return: paginated and extra response
        """

        serializer = self.get_serializer(page, many=True)

        if page is not None:
            response = self.get_paginated_response(serializer.data)
        else:
            response = serializer.data

        for key in extra.keys():
            response.data[key] = extra.get(key, None)

        return response

    def get_aggregated_data(self, queryset):
        """
        return a dictionary containing aggregated data of the given queryset
        """
        return {}

    def list(self, request, *args, **kwargs):
        """
        filter the given queryset
        generate some aggregate data
        return paginated data
        """
        queryset = self.filter_queryset(self.get_queryset())
        aggregated_data = self.get_aggregated_data(queryset=queryset)
        page = self.paginate_queryset(queryset)
        return self.get_extra_and_paginated_response(page, aggregated_data)


class ManagerialReport(RetrieveAPIView):
    """
        start datetime
        end datetime
        aggregation step


        **Managerial reports depend on a specific cafe
        therefore get_object must return the desired cafe
        that the reports may be generated for

    """

    class DateTimeException(Exception):
        pass

    def get_raw_report_params(self):
        """
        :return: {
            'start_datetime',
            'end_datetime',
            'step': 24 (this is default value),
        }
        """

        return {
            'start_datetime': self.request.query_params.get('start_datetime'),
            'end_datetime': self.request.query_params.get('end_datetime'),
            'step': self.request.query_params.get('step', 24)
        }

    def _validate_datetime(self, _datetime):
        """
        Convert _datetime start to actual python datetime objects

        catch any possible TypeError and ValueError exceptions and raise them as DateTimeException
        """
        try:
            return datetime.datetime.strptime(_datetime, "%Y-%m-%dT%H:%M")
        except (TypeError, ValueError) as e:
            if _datetime is None:
                raise self.DateTimeException("this field is required")
            else:
                raise self.DateTimeException(str(e))

    def validated_report_params(self):
        """
        :return: validate raw reports params and return validated data
        """
        raw_report_params = self.get_raw_report_params()
        errors = []

        # parse and validate start/end datetime s
        try:
            start_datetime = self._validate_datetime(raw_report_params.get('start_datetime'))
        except self.DateTimeException as e:
            errors.append({'start_datetime': [str(e), ]})

        try:
            end_datetime = self._validate_datetime(raw_report_params.get('end_datetime'))
        except self.DateTimeException as e:
            errors.append({'end_datetime': [str(e), ]})

        # validate step
        try:
            step = int(raw_report_params.get('step', 24))

            if step % 24 != 0:
                raise ValueError(_("step must be a multiple of 24 hours"))

            step = datetime.timedelta(hours=step)

        except (TypeError, ValueError) as e:
            errors.append({'step': [str(e), ]})

        # in report api's, start_datetime and end_datetime is required
        # and must be convertible to valid python datetime objects
        if not not errors:
            raise APIBadRequest(errors)

        # return the validate query_params data
        return {
            'start_datetime': start_datetime,
            'end_datetime': end_datetime,
            'step': step
        }

    def get_framed_queryset(self, start_datetime, end_datetime):
        """ count of items in the queryset that satisfies the given time constraints"""
        raise NotImplemented(_("Get framed queryset must be implemented"))

    def get_total_queryset_items(self):
        """Total number of items in an unbound (time wise) filter"""
        raise NotImplemented(_("Get total queryset items must be implemented"))

    def get_total_framed_items(self):
        """Total number of items in bounded (time wise) filter"""
        report_params = self.validated_report_params()

        return self.get_framed_queryset(report_params.get('start_datetime'),
                                        report_params.get('end_datetime'))

    def retrieve(self, request, *args, **kwargs):
        validated_params = self.validated_report_params()

        # extract report params
        start_datetime = validated_params.get('start_datetime')
        end_datetime = validated_params.get('end_datetime')
        step = validated_params.get('step')

        # total number of items in the given time frame
        total_bounded = self.get_total_framed_items()

        # total number of items in each step of the filter
        _start_datetime = start_datetime  # used inside the while loop that generates step by step aggregated reports

        step_results = []

        # calculate report result from start to end, excluding the last step
        while _start_datetime + step < end_datetime:
            queryset = self.get_framed_queryset(_start_datetime, _start_datetime + step)
            step_results.append(queryset)

            # increment counter start_datetime
            _start_datetime = _start_datetime + step

        # calculate the last step
        last_step = self.get_framed_queryset(_start_datetime, end_datetime)
        step_results.append(last_step)

        return Response({'total': self.get_total_queryset_items(),
                         'total_bounded': total_bounded,
                         'reports': step_results})


def kavenegar_send_sms(template, tokens, to):
    from cafepal import settings
    import requests

    if getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False):
        return

    api_endpoint = "https://api.kavenegar.com/v1/{API-KEY}/verify/lookup.json"
    api = furl(api_endpoint.replace('{API-KEY}', settings.KAVENEGAR_API_KEY))
    api.args['receptor'] = to
    api.args['template'] = template

    for key in tokens.keys():
        api.args[key] = tokens.get(key)

    print(api.url)
    requests.get(api.url)


def datetime_to_local_str(date_time):
    asia_tehran = pytz.timezone('Asia/Tehran')
    local_now = date_time.astimezone(asia_tehran)
    return JalaliDateTime.to_jalali(local_now).strftime('%y/%m/%dساعت%H:%M:%S')


def datetime_to_asia_tehran(date_time):
    asia_tehran = pytz.timezone('Asia/Tehran')
    return date_time.astimezone(asia_tehran)
