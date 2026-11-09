import json
import logging
import threading

import pytz
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import make_aware
from furl import furl
from rest_framework.response import Response
from rest_framework.views import APIView

from cafepal.secret import DEMO
from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import APIBadRequest, notify_watchers, _desktop_notification_thread, kavenegar_send_sms
from cafepay.api_v1.modules.payment.index import pg_functions
from cafepay.api_v1.modules.payment.payment_gates import PEP, LOCAL, ZIBAL, pg_gates_array, default_gate
from cafepay.models import Invoice, PBRPaymentSession, ProductBillRelation, TableToken, CafeWallet, Wallet
from django.utils.translation import gettext as _
import requests


logger = logging.getLogger(__name__)


class MakePayment(APIView):
    """
    Make payment takes an invoice
    the invoice will be prepared for payment based on the
    requested payment gate (if none is set, default payment gate will be used)
    and returns a payment url which client may be redirected to
    """

    def get_invoice(self):
        return get_object_or_404(Invoice, uuid=self.kwargs.get('invoice_uuid'))

    def get(self, request, *args, **kwargs):
        return self.prepare_invoice(request)

    def prepare_invoice(self, request):
        invoice = self.get_invoice()
        from cafepay.api_v1.modules.payment.mock import mock_enabled, prepare_mock_payment, is_mock_invoice
        if mock_enabled():
            return prepare_mock_payment(invoice, request)
        if is_mock_invoice(invoice):
            return Response({'details': 'Mock payments are disabled.'}, status=404)
        if DEMO or invoice.fake:
            return self.prepare_fake_invoice(invoice, request)
        else:
            return self.prepare_normal_invoice(invoice, request)

    @staticmethod
    def prepare_normal_invoice(invoice, request):
        """
        Normal Invoice is not fake
        Normal Invoices are prepared through an actual payment gate
        :param invoice:
        :param request:
        :return:
        """

        if invoice.use_default_gate:
            gate = default_gate
        else:
            gate = invoice.payment_gate
            if not gate or gate not in pg_gates_array:
                return Response({'details': _("Invalid payment gate ")}, status=400)

        prepare_for_payment = pg_functions.get(gate, {}).get('prepare_for_payment')
        if prepare_for_payment is None:
            return Response({'details': _("Invalid payment gate ")}, status=400)
        prepare_result = prepare_for_payment(invoice, request)
        return Response(prepare_result, status=prepare_result.get('status', 500))

    @staticmethod
    def prepare_fake_invoice(invoice, request):
        """
        Prepare the given invoice using LOCAL gateway
        :param invoice:
        :param request:
        :return:
        """
        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
            if invoice.status not in (InvoiceConsts.PAYED, InvoiceConsts.REFUNDED):
                invoice.status = InvoiceConsts.IN_PAYMENT
                invoice.save(update_fields=['status'])
        verify_url = reverse("payment_verify", kwargs={'invoice_uuid': invoice.uuid, 'pg': LOCAL})
        url = request.build_absolute_uri(verify_url)
        return Response({'redirect_to': url, 'status': 200})


class VerifyPayment(APIView):
    """
    Verifies a Bank payment based on payment gate and invoice uuid
    after verification on the bank side, based on invoice tag
    a "after verification function" will be called

    for example:
     - user has 2$ on his wallet
     - user wants to pay 4$ on an espresso and 6$ on a mocha

     . a PBRPaymentSession will be created for the user
     which includes a 4$ payment on the espresso PBR and a 6$
     payment on the mocha PBR
     . from this PBR session, an Invoice of amount (10$ - 2$ =) 8$
     and a tag of PAY_FOR_SESSION will be created.

     . this user will be redirected to IPG with an amount of 8$
     upon returning from bank, the 8$ transaction must be verified

     . after verification user must be notified that his account was
     withdrawn by 10$

    """

    def get_invoice(self):
        return get_object_or_404(Invoice, uuid=self.kwargs.get('invoice_uuid'))

    @staticmethod
    def validate_invoice(invoice, pg):
        if DEMO or invoice.fake:
            return True, ""
        verifier = pg_functions.get(pg, {}).get('verify_payment')
        if verifier is None:
            return False, _('Invalid payment gate')
        result = verifier(invoice)
        # Historical gateway adapters return either a boolean or a result pair.
        return result if isinstance(result, tuple) else (bool(result), '')

    @staticmethod
    def stored_result(invoice):
        if invoice.tag == InvoiceConsts.PAY_PBR_SESSION:
            session = get_object_or_404(PBRPaymentSession, invoice=invoice)
            if not invoice.payment_session_id:
                return _('این پرداخت به بررسی نیاز دارد'), 400, session.total_amount
            settled = Invoice.objects.filter(payment_session=invoice.payment_session,
                tag=InvoiceConsts.PAYED_FOR_PRODUCT, type=InvoiceConsts.DEPOSIT,
                status__in=(InvoiceConsts.PAYED, InvoiceConsts.INTERNAL)).aggregate(total=Sum('amount'))['total'] or 0
            if settled != session.total_amount:
                return _('پرداخت تأیید شده است؛ مانده کیف پول و سفارش را بررسی کنید.'), 400, session.total_amount
            return _('پرداخت با موفقیت انجام شد'), 200, session.total_amount
        if invoice.tag == InvoiceConsts.CHARGE_WALLET:
            return _('کیف پول شارژ شد'), 200, invoice.amount
        return _('Invalid invoice tag'), 400, invoice.amount

    @staticmethod
    def notify_completed(cafe, session):
        try:
            cafe.notify_payments(session, date_time=timezone.now())
        except Exception:
            logger.warning('Payment notification failed after settlement')

    def get(self, request, *args, **kwargs):
        """
        redirect to https://alpha.cafepay.app/paymentResult
        with the following as params

        {
            'status': 200 | 400,
            'amount': amount,
            'uuid': uuid,
            'description': "some description"
        }
        """

        redirect_to = self.get_redirect_to(request)

        invoice = self.get_invoice()
        pg = self.get_payment_gate(kwargs)

        # A mock callback only displays an outcome. Settlement requires an
        # explicit, CSRF-protected approval on the local gateway page.
        from cafepay.api_v1.modules.payment.mock import mock_enabled, is_mock_invoice, mock_result
        if mock_enabled():
            if pg != LOCAL or not is_mock_invoice(invoice):
                return Response({'details': 'Invalid mock payment.'}, status=400)
            return mock_result(invoice, request)
        if is_mock_invoice(invoice):
            return Response({'details': 'Mock payments are disabled.'}, status=404)

        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
            if (invoice.type != InvoiceConsts.DEPOSIT or invoice.method != InvoiceConsts.ONLINE or
                    invoice.tag not in (InvoiceConsts.PAY_PBR_SESSION, InvoiceConsts.CHARGE_WALLET)):
                return Response({'details': _('Invalid payable invoice')}, status=400)
            if invoice.status == InvoiceConsts.PAYED:
                notes, success, amount = self.stored_result(invoice)
            elif invoice.status == InvoiceConsts.REFUNDED:
                notes, success, amount = _('این پرداخت بازپرداخت شده است'), 400, invoice.amount
            else:
                valid, message = self.validate_invoice(invoice, pg)
                if valid:
                    # Commit the verified gateway credit even if order allocation fails.
                    invoice.status = InvoiceConsts.PAYED
                    invoice.save(update_fields=['status'])
                    if invoice.tag == InvoiceConsts.PAY_PBR_SESSION:
                        try:
                            with transaction.atomic():
                                amount, cafe, notes, session, success = self.process_payment_session(invoice, pg)
                        except Exception:
                            logger.warning('Order allocation failed after gateway verification')
                            notes, success, amount = self.stored_result(invoice)
                        else:
                            if success == 200:
                                transaction.on_commit(lambda: self.notify_completed(cafe, session))
                    elif invoice.tag == InvoiceConsts.CHARGE_WALLET:
                        notes, success, amount = _('کیف پول شارژ شد'), 200, invoice.amount
                    else:
                        notes, success, amount = _('Invalid invoice tag'), 400, invoice.amount
                else:
                    notes, success, amount = message, 400, invoice.amount

        self.add_args_to_redirect_to(amount, invoice, notes, redirect_to, success)

        return HttpResponseRedirect(redirect_to.url)

    def get_payment_gate(self, kwargs):
        pg = kwargs.get('pg', None)
        if pg not in pg_gates_array:
            raise APIBadRequest(_("Invalid Payment Gate"))
        return pg

    @staticmethod
    def add_args_to_redirect_to(amount, invoice, notes, redirect_to, success):
        redirect_to.args['status'] = success
        redirect_to.args['amount'] = amount
        redirect_to.args['uuid'] = invoice.uuid
        redirect_to.args['description'] = notes

        if invoice.extra:
            redirect_to.args['table_type'] = TableToken.SELF_PICKUP if invoice.extra.is_preorder else TableToken.NORMAL
            redirect_to.args['table_uuid'] = invoice.extra.uuid

    def process_payment_session(self, invoice, pg):
        session = get_object_or_404(PBRPaymentSession, invoice=invoice)
        payment = session.payments.first()
        cafe = payment.pbr.bill.table.cafe
        notes, success, amount = pay_for_session(session, invoice)
        if success == 400:
            self.refund_payment(invoice, pg)
        return amount, cafe, notes, session, success

    @staticmethod
    def get_redirect_to(request):
        if getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False):
            return furl(settings.CAFEPAY_FRONTEND_URL.rstrip('/') + '/paymentResult/')
        host = request.META.get('HTTP_HOST')
        host = host.replace('main.', '')
        redirect_to = furl('https://%s/paymentResult' % host)
        return redirect_to

    @staticmethod
    def refund_payment(invoice, pg):
        return
        refund_func = pg_functions.get(pg).get('refund_payment')
        if refund_func:
            VerifyPayment.refund_payment_through_pg(invoice, refund_func)

    @staticmethod
    def refund_payment_through_pg(invoice, refund_func):
        result = refund_func(invoice)
        VerifyPayment.notify_refund_with_sms(result)
        VerifyPayment.update_invoice_status_to_rejected(invoice, result)

    @staticmethod
    def update_invoice_status_to_rejected(invoice, result):
        if result:
            invoice.status = InvoiceConsts.REJECTED
            invoice.save()

    @staticmethod
    def notify_refund_with_sms(result):
        kavenegar_send_sms("refundException",
                           {'token': "error" + str(result)},
                           "09171164364")
        kavenegar_send_sms("refundException",
                           {'token': "error" + str(result)},
                           "09017938091")

    @staticmethod
    def desktop_notify(table):
        # if table is preorder, desktop notify if payment is done
        if table.is_preorder:
            active_join = table.active_join
            payment_info = active_join.payment_info

            if payment_info.get('net_amount') == 0:
                thread2 = threading.Thread(target=_desktop_notification_thread, args=(table,))
                thread2.start()


def pay_for_session(session, invoice):
    """

    :param session:
    :param invoice:
    :return: notes, success, amount
    """
    notes = _("Payment successful")

    try:
        settled_amount = 0
        with transaction.atomic():
            payments = list(session.payments.order_by('pbr_id', 'pk'))
            if not payments:
                raise APIBadRequest(_('Cannot pay an empty session'))
            # Match manual-payment lock ordering before any wallet is acquired.
            pbrs = {pbr.pk: pbr for pbr in ProductBillRelation.objects.select_for_update()
                    .filter(pk__in=[payment.pbr_id for payment in payments]).order_by('pk')}
            first_pbr = pbrs[payments[0].pbr_id]
            cafe_wallet, wallet = get_or_create_user_profile_cafe_wallet(first_pbr, session)
            cafe = first_pbr.bill.table.cafe
            # Balance reads acquire locks too. Acquire all wallets before reading any.
            list(Wallet.objects.select_for_update().filter(
                pk__in=[wallet.pk, cafe_wallet.wallet_id, cafe.wallet_id]).order_by('pk'))
            for payment in payments:
                pbr = pbrs[payment.pbr_id]

                # ignore this pbr if payment is complete
                if pbr.remaining_amount <= 0:
                    continue

                payment_amount = get_payment_amount(payment, pbr)
                amount_from_cafe_wallet = amount_to_be_payed_from_user_profile_cafe_wallet(
                    cafe_wallet, payment_amount)

                # if anything remains try to withdraw from users main wallet
                remaining_amount = payment_amount - amount_from_cafe_wallet
                settled_amount += payment_amount
                make_transfer_payment_to_cafe(amount_from_cafe_wallet, cafe_wallet, pbr,
                                              remaining_amount, wallet, invoice.payment_session)
            # Gateway credit can combine with existing wallet funds.
            # Reconcile the order allocation, not only the new credit amount.
            if settled_amount != session.total_amount:
                raise APIBadRequest(_("Invalid Invoice Amount Usage"))

            # send delivery fee
            if invoice.delivery_fee != 0:
                owner = pbr.bill.current_owner
                delivery_join = owner.join if owner else pbr.bill.join
                if delivery_join is None:
                    raise APIBadRequest(_('The payment order has no destination'))
                transfer_amount_from(wallet_of_user_profile(session), invoice.delivery_fee, **{
                    'to': wallet_of_cafe(session),
                    'status': InvoiceConsts.INTERNAL,
                    'tag': InvoiceConsts.DELIVERY_FEE,
                    'item': delivery_join,
                    'payment_session': invoice.payment_session,
                })

            # clear the invoice if has target sheba
            if invoice.auto_clear and invoice.sub_payment_target_sheba:
                add_clear_invoice_for_cafe(invoice, session)

        status = 200
    except APIBadRequest as e:
        notes = str(e)
        status = 400

    amount = session.total_amount
    return notes, status, amount


def make_transfer_payment_to_cafe(amount_from_cafe_wallet, cafe_wallet, pbr, remaining_amount, wallet, payment_session):
    transfer_data = {
        'to': pbr.product.cafe.wallet,
        'status': InvoiceConsts.INTERNAL,
        'tag': InvoiceConsts.PAYED_FOR_PRODUCT,
        'payment_session': payment_session,
        'item': pbr
    }
    # attempt to transfer amount if amount is not 0
    if amount_from_cafe_wallet != 0:
        transfer_amount_from(cafe_wallet.wallet, amount_from_cafe_wallet, **transfer_data)
    if remaining_amount != 0:
        transfer_amount_from(wallet, remaining_amount, **transfer_data)


def get_amount_from_user_profile_cafe_wallet(payment_amount, pbr, session):
    cafe_wallet, wallet = get_or_create_user_profile_cafe_wallet(pbr, session)
    amount_from_cafe_wallet = amount_to_be_payed_from_user_profile_cafe_wallet(cafe_wallet, payment_amount)
    return amount_from_cafe_wallet, cafe_wallet, wallet


def amount_to_be_payed_from_user_profile_cafe_wallet(cafe_wallet, payment_amount):
    # use cafe_wallet first
    # if there is enough balance in the cafe wallet
    # pay the whole payment_amount from cafe wallet
    if cafe_wallet.wallet.balance >= payment_amount:
        amount_from_cafe_wallet = payment_amount
    # if cafe wallet balance is not enough, use all of it
    else:
        amount_from_cafe_wallet = cafe_wallet.wallet.balance
    return amount_from_cafe_wallet


def get_or_create_user_profile_cafe_wallet(pbr, session):
    # get or create cafe wallet
    cafe_wallet = CafeWallet.get_or_create(user_profile=session.user_profile,
                                           cafe=pbr.bill.table.cafe)
    wallet = session.user_profile.wallet
    return cafe_wallet, wallet


def wallet_of_user_profile(session):
    return session.user_profile.wallet


def wallet_of_cafe(session):
    for payment in session.payments.all():
        pbr = ProductBillRelation.objects.get(pk=payment.pbr.pk)
        return pbr.bill.table.cafe.wallet


def transfer_amount_from(from_wallet, amount, **transfer_data):
    if not from_wallet.transfer(amount=amount, **transfer_data):
        raise APIBadRequest(_("Could not complete payment."
                              " your account has not been credited."))


def add_clear_invoice_for_cafe(invoice, session):
    payment = session.payments.first()
    cafe = payment.pbr.bill.table.cafe
    Invoice.objects.create(
        payment_session=invoice.payment_session,
        wallet=cafe.wallet,
        amount=session.total_amount + invoice.delivery_fee,
        cafepay_fee=invoice.cafepay_fee,
        fee_payer=invoice.fee_payer,
        type=InvoiceConsts.CLEARING,
        status=InvoiceConsts.PAYED,
        tag=InvoiceConsts.CLEARING_TAG,
        method=InvoiceConsts.ONLINE,
    )


def get_payment_amount(payment, pbr):
    # avoid extra payments on pbr
    if pbr.remaining_amount < payment.amount:
        payment_amount = pbr.remaining_amount
    else:
        payment_amount = payment.amount
    return payment_amount
