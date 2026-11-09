"""Local-only payment UI, backed by the real invoice and order ledger."""
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from rest_framework.response import Response

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.modules.payment.payment_gates import LOCAL

logger = logging.getLogger(__name__)


def mock_enabled():
    return (getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False) and
            getattr(settings, 'CAFEPAY_MOCK_PAYMENTS', False))


def is_mock_invoice(invoice):
    return invoice.payment_gate == LOCAL and (invoice.token or '').startswith('mock_')


def checkout_url(invoice, request):
    path = reverse('mock_payment', kwargs={'invoice_uuid': invoice.uuid})
    return request.build_absolute_uri(path) + '?' + urlencode({'token': invoice.token})


def prepare_mock_payment(invoice, request):
    from cafepay.models import Invoice
    if not mock_enabled():
        raise Http404
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if (invoice.type != InvoiceConsts.DEPOSIT or invoice.method != InvoiceConsts.ONLINE or
                invoice.tag not in (InvoiceConsts.PAY_PBR_SESSION, InvoiceConsts.CHARGE_WALLET)):
            return Response({'details': 'Not a payable invoice.'}, status=400)
        if invoice.status == InvoiceConsts.PAYED:
            if not is_mock_invoice(invoice):
                return Response({'details': 'Invoice is already paid.'}, status=409)
        elif invoice.status in (InvoiceConsts.CREATED, InvoiceConsts.REJECTED, InvoiceConsts.IN_PAYMENT):
            if (invoice.status != InvoiceConsts.IN_PAYMENT or not is_mock_invoice(invoice) or
                    expired(invoice)):
                invoice.token = 'mock_' + secrets.token_urlsafe(32)
                invoice.payment_gate = LOCAL
                invoice.status = InvoiceConsts.IN_PAYMENT
                invoice.last_payment_timestamp = timezone.now()
                invoice.save(update_fields=['token', 'payment_gate', 'status', 'last_payment_timestamp'])
        else:
            return Response({'details': 'Invoice cannot be paid.'}, status=409)
        return Response({'redirect_to': checkout_url(invoice, request), 'status': 200, 'mock': True})


def expired(invoice):
    return (not invoice.last_payment_timestamp or
            timezone.now() - invoice.last_payment_timestamp > timedelta(minutes=30))


def mock_result(invoice, request):
    from cafepay.api_v1.views.PaymentViews import VerifyPayment
    paid = invoice.status == InvoiceConsts.PAYED
    redirect = VerifyPayment.get_redirect_to(request)
    VerifyPayment.add_args_to_redirect_to(
        invoice.amount + invoice.delivery_fee, invoice,
        'پرداخت آزمایشی با موفقیت انجام شد' if paid else 'پرداخت آزمایشی رد شد یا تکمیل نشد',
        redirect, 200 if paid else 400)
    redirect.args['mock'] = 'true'
    return HttpResponseRedirect(redirect.url)


def notify_payment(cafe, session):
    # A notification failure must not turn an already committed sale into a 500.
    try:
        cafe.notify_payments(session, date_time=timezone.now())
    except Exception:
        logger.exception('Local payment notification failed')


class SettlementFailed(Exception):
    pass


@method_decorator(never_cache, name='dispatch')
class MockPaymentGateway(View):
    """The opaque checkout URL authorizes this form; Django enforces CSRF on POST."""

    def get_invoice(self, request, invoice_uuid, lock=False):
        from cafepay.models import Invoice
        if not mock_enabled():
            raise Http404
        invoices = Invoice.objects.select_for_update() if lock else Invoice.objects.all()
        invoice = get_object_or_404(invoices, uuid=invoice_uuid)
        token = request.POST.get('token', '') if request.method == 'POST' else request.GET.get('token', '')
        if not is_mock_invoice(invoice) or not constant_time_compare(invoice.token, token):
            raise Http404
        return invoice

    def get(self, request, invoice_uuid):
        invoice = self.get_invoice(request, invoice_uuid)
        if invoice.status in (InvoiceConsts.PAYED, InvoiceConsts.REJECTED):
            return mock_result(invoice, request)
        if expired(invoice):
            return JsonResponse({'details': 'Checkout expired. Start payment again.'}, status=410)
        response = render(request, 'mock_payment.html', {
            'invoice': invoice, 'total': invoice.amount + invoice.delivery_fee,
        })
        response['Referrer-Policy'] = 'no-referrer'
        return response

    def post(self, request, invoice_uuid):
        from cafepay.api_v1.views.PaymentViews import VerifyPayment
        decision = request.POST.get('decision')
        if decision not in ('approve', 'decline'):
            return JsonResponse({'details': 'Choose approve or decline.'}, status=400)
        try:
            with transaction.atomic():
                invoice = self.get_invoice(request, invoice_uuid, lock=True)
                # The row lock and terminal-state check also protect delivery fees
                # and wallet-only payments against concurrent/replayed submissions.
                if invoice.status in (InvoiceConsts.PAYED, InvoiceConsts.REJECTED):
                    return mock_result(invoice, request)
                if invoice.status != InvoiceConsts.IN_PAYMENT or expired(invoice):
                    return JsonResponse({'details': 'Checkout expired. Start payment again.'}, status=410)
                if decision == 'decline':
                    invoice.status = InvoiceConsts.REJECTED
                    invoice.save(update_fields=['status'])
                else:
                    invoice.status = InvoiceConsts.PAYED
                    invoice.transId = 'MOCK-' + str(invoice.uuid)
                    invoice.card_number = 'MOCK (no card charged)'
                    invoice.save(update_fields=['status', 'transId', 'card_number'])
                    if invoice.tag == InvoiceConsts.PAY_PBR_SESSION:
                        _, cafe, notes, session, status = VerifyPayment().process_payment_session(invoice, LOCAL)
                        if status != 200:
                            raise SettlementFailed(str(notes))
                        transaction.on_commit(lambda: notify_payment(cafe, session))
                return mock_result(invoice, request)
        except SettlementFailed as error:
            # Roll back BOTH the gateway credit and all order transfers. The
            # checkout stays pending so a corrected order can be retried.
            return JsonResponse({'details': str(error)}, status=409)
