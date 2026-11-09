"""Non-mock callbacks settle once and preserve verified credits on failure."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.modules.payment.payment_gates import LOCAL, VANDAR
from cafepay.api_v1.views.PaymentViews import MakePayment, VerifyPayment
from cafepay.models import (CafeRegionPrice, City, Invoice, PBRPaymentSession, ProductBillRelation,
                           Region, UserProfileAddress)
from cafepay.test_backend_support import BackendFixtures


class CallbackFixtures(BackendFixtures):
    def setUp(self):
        super().setUp()
        demo = patch('cafepay.api_v1.views.PaymentViews.DEMO', False)
        demo.start()
        self.addCleanup(demo.stop)
        notify = patch('cafepay.models.Cafe.notify_payments')
        self.notification = notify.start()
        self.addCleanup(notify.stop)

    def checkout(self, balance=0, delivery=False):
        if delivery:
            region = Region.objects.create(city=City.objects.create(name='Test'), name='Test')
            self.join.include_delivery_fee = True
            self.join.address = UserProfileAddress.objects.create(
                region=region, user_profile=self.customer, address='Test')
            self.join.save()
            CafeRegionPrice.objects.create(cafe=self.cafe, region=region, price=5000)
        if balance:
            self.customer.wallet.deposit(amount=balance, status=InvoiceConsts.PAYED)
        self.authenticate(self.customer)
        with override_settings(CAFEPAY_MOCK_PAYMENTS=True):
            response = self.client.post('/api/v1/pbr/session/create/', {
                'payments': [{'pbr': self.pbr.pk, 'amount': 20000}], 'use_wallet': True,
            }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return PBRPaymentSession.objects.get(pk=response.data['pk']).invoice

    def callback(self, invoice):
        request = APIRequestFactory().get('/callback/')
        return VerifyPayment.as_view()(request, invoice_uuid=invoice.uuid, pg=LOCAL)

    def outcome(self, response):
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlsplit(response.url).query)['status'][0]


@override_settings(CAFEPAY_LOCAL_RECOVERY=True, CAFEPAY_MOCK_PAYMENTS=False)
class PaymentCallbackTests(CallbackFixtures, TestCase):
    def test_fake_delivery_callback_replay_never_charges_again(self):
        invoice = self.checkout(30000, delivery=True)
        self.assertTrue(invoice.fake)
        request = APIRequestFactory().get('/prepare/')
        MakePayment.prepare_fake_invoice(invoice, request)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceConsts.IN_PAYMENT)
        self.assertEqual(self.customer.wallet.balance, 30000)
        self.assertEqual(self.outcome(self.callback(invoice)), '200')
        count = Invoice.objects.count()
        self.assertEqual(self.outcome(self.callback(invoice)), '200')
        self.assertEqual(Invoice.objects.count(), count)
        self.assertEqual(self.customer.wallet.balance, 5000)
        self.assertEqual(self.cafe.wallet.balance, 25000)

    def test_gateway_callback_replay_does_not_reverify_or_transfer(self):
        invoice = self.checkout(5000)
        with patch.object(VerifyPayment, 'validate_invoice', return_value=(True, '')) as verify:
            self.assertEqual(self.outcome(self.callback(invoice)), '200')
            count = Invoice.objects.count()
            self.assertEqual(self.outcome(self.callback(invoice)), '200')
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(Invoice.objects.count(), count)
        self.assertEqual(self.cafe.wallet.balance, 20000)
        self.assertEqual(self.customer.wallet.balance, 0)

    def test_failed_order_allocation_preserves_gateway_credit(self):
        invoice = self.checkout()
        ProductBillRelation.objects.filter(pk=self.pbr.pk).update(count=1)
        with patch.object(VerifyPayment, 'validate_invoice', return_value=(True, '')) as verify:
            self.assertEqual(self.outcome(self.callback(invoice)), '400')
            self.assertEqual(self.outcome(self.callback(invoice)), '400')
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(self.customer.wallet.balance, 20000)
        self.assertEqual(self.cafe.wallet.balance, 0)

    def test_boolean_gateway_results_are_normalized(self):
        invoice = self.checkout()
        with patch.dict('cafepay.api_v1.views.PaymentViews.pg_functions', {
                VANDAR: {'verify_payment': lambda invoice: True}}):
            self.assertEqual(VerifyPayment.validate_invoice(invoice, VANDAR), (True, ''))
        self.assertEqual(VerifyPayment.validate_invoice(invoice, LOCAL)[0], False)

    def test_internal_invoices_cannot_be_verified_as_gateway_deposits(self):
        invoice = self.cafe.wallet.deposit(amount=1000, status=InvoiceConsts.CREATED,
            method=InvoiceConsts.CASH, tag=InvoiceConsts.PAYED_FOR_PRODUCT, item=self.pbr)
        with patch.object(VerifyPayment, 'validate_invoice') as verify:
            self.assertEqual(self.callback(invoice).status_code, 400)
        verify.assert_not_called()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceConsts.CREATED)


@override_settings(CAFEPAY_LOCAL_RECOVERY=True, CAFEPAY_MOCK_PAYMENTS=False)
class ConcurrentPaymentCallbackTests(CallbackFixtures, TransactionTestCase):
    def test_concurrent_callbacks_share_one_verification_and_settlement(self):
        invoice = self.checkout(30000, delivery=True)
        start = Barrier(2)
        def callback(_):
            close_old_connections()
            try:
                start.wait(timeout=10)
                return self.outcome(self.callback(invoice))
            finally:
                close_old_connections()
        with patch.object(VerifyPayment, 'validate_invoice', return_value=(True, '')) as verify:
            with ThreadPoolExecutor(max_workers=2) as workers:
                self.assertEqual(list(workers.map(callback, range(2))), ['200', '200'])
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(self.customer.wallet.balance, 5000)
        self.assertEqual(self.cafe.wallet.balance, 25000)
        self.assertEqual(self.notification.call_count, 1)
