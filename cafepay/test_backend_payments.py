"""Payment batches must preserve order balances and cafe boundaries."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.serializers.PBRPaymentSerializers import PBRPaymentManualSessionCreateSerializer
from cafepay.models import Invoice, PBRPaymentSession
from cafepay.test_backend_support import BackendFixtures


class ManualPaymentTests(BackendFixtures, TestCase):
    def test_duplicate_and_zero_manual_payments_leave_ledger_unchanged(self):
        self.authenticate(self.staff)
        url = '/api/v1/pbr/session/%s/create/' % self.cafe.pk
        item = {'pbr': self.pbr.pk, 'amount': self.pbr.remaining_amount}
        for payments in ([item, item], [dict(item, amount=0)]):
            response = self.client.post(url, {'payments': payments, 'method': InvoiceConsts.CASH}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertFalse(Invoice.objects.exists())
            self.assertFalse(PBRPaymentSession.objects.exists())
        response = self.client.post(url, {'payments': [item], 'method': InvoiceConsts.CASH}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.pbr.remaining_amount, 0)
        self.assertEqual(self.cafe.wallet.balance, 20000)


class ConcurrentPaymentTests(BackendFixtures, TransactionTestCase):
    def test_concurrent_full_payments_cannot_credit_twice(self):
        ready = Barrier(2)

        def pay():
            close_old_connections()
            try:
                serializer = PBRPaymentManualSessionCreateSerializer(data={
                    'payments': [{'pbr': self.pbr.pk, 'amount': 20000}],
                    'method': InvoiceConsts.CASH,
                }, context={'view': SimpleNamespace(kwargs={'cafe_id': self.cafe.pk})})
                serializer.is_valid(raise_exception=True)
                ready.wait(timeout=10)
                try:
                    serializer.save(user_profile=self.staff)
                    return 'paid'
                except ValidationError:
                    return 'rejected'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: pay(), range(2)))
        self.assertCountEqual(results, ['paid', 'rejected'])
        self.assertEqual(self.cafe.wallet.balance, 20000)
        self.assertEqual(self.pbr.remaining_amount, 0)
        self.assertEqual(PBRPaymentSession.objects.count(), 1)


@override_settings(CAFEPAY_LOCAL_RECOVERY=True, CAFEPAY_MOCK_PAYMENTS=True)
class OnlinePaymentScopeTests(BackendFixtures, TestCase):
    def test_checkout_rejects_duplicate_mixed_and_closed_orders(self):
        from cafepay.models import Bill, Table, TableJoin, ProductBillRelation
        self.authenticate(self.customer)
        other_table = Table.objects.create(cafe=self.other_cafe, number='2')
        other_join = TableJoin.objects.create(cafe=self.other_cafe)
        other_bill = Bill.objects.create(table=other_table, join=other_join)
        other_product = self.make_product(self.other_cafe, self.other_staff)
        other_pbr = ProductBillRelation.objects.create(
            bill=other_bill, product=other_product, user_profile=self.customer,
            count=1, original_price=10000, discount=0)
        first = {'pbr': self.pbr.pk, 'amount': 10000}
        second = {'pbr': other_pbr.pk, 'amount': 10000}
        url = '/api/v1/pbr/session/create/'
        for payments in ([first, first], [first, second]):
            response = self.client.post(url, {'payments': payments, 'use_wallet': False}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertFalse(Invoice.objects.exists())
        other_bill.table = self.table
        other_bill.join = self.join
        other_bill.save()
        other_pbr.product = self.product
        other_pbr.save()
        response = self.client.post(url, {'payments': [first, second], 'use_wallet': False}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.join.force_close = True
        self.join.save()
        response = self.client.post(url, {'payments': [first], 'use_wallet': False}, format='json')
        self.assertEqual(response.status_code, 400, response.data)


class WalletInvoiceTests(BackendFixtures, TestCase):
    def test_wallet_rejects_zero_charges_and_returns_real_dates(self):
        self.authenticate(self.customer)
        url = '/api/v1/user-profile/wallet/charge/'
        for amount in (0, -1):
            response = self.client.post(url, {'amount': amount}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Invoice.objects.exists())
        response = self.client.post(url, {'amount': 1000}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        wallet = self.client.get('/api/v1/user-profile/wallet/').data['wallet']
        self.assertEqual(wallet['balance'], 0)
        self.assertEqual(wallet['invoice'][0]['amount'], 1000)
        self.assertTrue(wallet['invoice'][0]['create_datetime'])


class RefundValidationTests(BackendFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.invoice = self.cafe.wallet.deposit(amount=20000, status=InvoiceConsts.PAYED,
            method=InvoiceConsts.CASH, tag=InvoiceConsts.PAYED_FOR_PRODUCT, item=self.pbr)
        self.authenticate(self.staff)

    def test_duplicate_and_unrelated_refunds_do_not_change_wallet(self):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from cafepay.api_v1.views.PBRPaymentViews import PBRInternalRefundView
        def submit(refunds):
            request = APIRequestFactory().post('/disabled-refund/', {'refunds': refunds}, format='json')
            force_authenticate(request, user=self.staff.django_user)
            return PBRInternalRefundView.as_view()(request, cafe_id=self.cafe.pk)
        item = {'pbr': self.pbr.pk, 'invoice': self.invoice.pk, 'amount': 20000}
        unrelated = Invoice.objects.create(wallet=self.cafe.wallet, amount=20000)
        for refunds in ([item, item], [dict(item, invoice=unrelated.pk)]):
            response = submit(refunds)
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(self.cafe.wallet.balance, 20000)
        response = submit([item])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.cafe.wallet.balance, 0)
        self.assertEqual(self.pbr.net_payed_amount, 0)
        self.assertEqual(submit([item]).status_code, 400)

    def test_online_invoice_query_excludes_manual_sessions_and_deduplicates(self):
        from cafepay.models import PBRPayment
        manual = PBRPaymentSession.objects.create(user_profile=self.customer, is_manual=True)
        PBRPayment.objects.create(session=manual, pbr=self.pbr, amount=1000)
        online_invoice = Invoice.objects.create(wallet=self.customer.wallet, amount=20000,
            status=InvoiceConsts.PAYED, type=InvoiceConsts.DEPOSIT, method=InvoiceConsts.ONLINE)
        online = PBRPaymentSession.objects.create(user_profile=self.customer, invoice=online_invoice)
        for _ in range(2):
            PBRPayment.objects.create(session=online, pbr=self.pbr, amount=10000)
        with self.assertNumQueries(1):
            invoices = list(self.join.get_all_online_payed_invoices())
        self.assertEqual([invoice.pk for invoice in invoices], [online_invoice.pk])


class ConcurrentRefundTests(BackendFixtures, TransactionTestCase):
    def test_concurrent_refunds_cannot_withdraw_same_payment_twice(self):
        from cafepay.api_v1.serializers.PBRPaymentSerializers import PBRInternalRefundSerializer
        from cafepay.api_v1.views.PBRPaymentViews import PBRInternalRefundView
        from cafepay.models import PBRRefund
        invoice = self.cafe.wallet.deposit(amount=20000, status=InvoiceConsts.PAYED,
            method=InvoiceConsts.CASH, tag=InvoiceConsts.PAYED_FOR_PRODUCT, item=self.pbr)
        # Extra cafe funds make a missing balance recheck observable.
        self.cafe.wallet.deposit(amount=20000, status=InvoiceConsts.PAYED)
        ready = Barrier(2)
        def refund(_):
            close_old_connections()
            try:
                view = PBRInternalRefundView()
                view.kwargs = {'cafe_id': self.cafe.pk}
                serializer = PBRInternalRefundSerializer(data={'refunds': [{
                    'pbr': self.pbr.pk, 'invoice': invoice.pk, 'amount': 20000,
                }]}, context={'view': view})
                serializer.is_valid(raise_exception=True)
                ready.wait(timeout=10)
                try:
                    view.perform_create(serializer)
                    return 'refunded'
                except ValidationError:
                    return 'rejected'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(refund, range(2)))
        self.assertCountEqual(results, ['refunded', 'rejected'])
        self.assertEqual(self.cafe.wallet.balance, 20000)
        self.assertEqual(PBRRefund.objects.count(), 1)
