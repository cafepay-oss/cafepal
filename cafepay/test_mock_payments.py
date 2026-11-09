"""Product-to-sale HTTP regression tests against an isolated Django test database.

Run with ``./local test``. Requests use the real HTTP server, authentication,
serializers, payment form, CSRF middleware and ledger. Notification delivery is
stubbed; browser JavaScript, Redis and restored production data are not tested.
"""
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from cafepay.api_v1.consts import CharacterFieldConsts, InvoiceConsts
from cafepay.models import (Cafe, CharacterField, Invoice, Menu, Product,
                           ProductBillRelation, Table, TableToken, UserProfile,
                           Wallet)


@override_settings(CAFEPAY_LOCAL_RECOVERY=True, CAFEPAY_MOCK_PAYMENTS=True,
                   CAFEPAY_FRONTEND_URL='http://localhost:3000')
class MockSaleHTTPTests(LiveServerTestCase):
    def setUp(self):
        # Only transport side effects are stubbed. Ledger and settlement are real.
        notifier = patch('cafepay.api_v1.views.TableViews.notify_watchers')
        notifier.start()
        self.addCleanup(notifier.stop)
        payments = patch('cafepay.api_v1.modules.payment.mock.notify_payment')
        self.notifications = payments.start()
        self.addCleanup(payments.stop)

        self.staff, self.manager = self.make_user('manager', '09000000001', True)
        self.buyer, self.customer = self.make_user('customer', '09000000002')
        self.gateway = self.http_session()
        self.cafe = Cafe.objects.create(
            name='HTTP test cafe', address='Local test database',
            wallet=Wallet.objects.create(), is_active=True,
            menu_prices_on=True, menu_items_on=True, cafepay_fee=0)
        self.menu = Menu.objects.create(name='Test menu', cafe=self.cafe,
                                        staff=self.staff, is_active=True)
        self.category = CharacterField.objects.create(
            title='Coffee', type=CharacterFieldConsts.CATEGORY,
            cafe=self.cafe, staff=self.staff, menu=self.menu)
        self.table = Table.objects.create(cafe=self.cafe, number='Test table',
                                          uuid=uuid4(), staff=self.staff)
        self.table_token = TableToken.objects.create(
            cafe=self.cafe, table=self.table, status=TableToken.ACTIVE)

    def http_session(self):
        session = requests.Session()
        session.trust_env = False
        self.addCleanup(session.close)
        return session

    def make_user(self, name, phone, staff=False):
        user = User.objects.create_user(username=name, password='local-test-only',
                                        is_staff=staff, is_superuser=staff)
        profile = UserProfile.objects.create(django_user=user, phone_number=phone,
                                              wallet=Wallet.objects.create())
        session = self.http_session()
        session.headers['Authorization'] = 'Token ' + Token.objects.create(user=user).key
        return profile, session

    def request(self, session, method, path, expected=200, **kwargs):
        url = path if path.startswith('http://') else self.live_server_url + path
        # Never follow the checkout redirect out of the isolated HTTP test server.
        self.assertEqual(urlsplit(url).netloc, urlsplit(self.live_server_url).netloc)
        response = session.request(method, url, timeout=15, allow_redirects=False, **kwargs)
        self.assertEqual(response.status_code, expected, response.text[:1500])
        return response

    def create_order(self, quantity=2):
        product = self.request(self.manager, 'POST', reverse('product_create', kwargs={
            'cafe_id': self.cafe.pk}), expected=201, json={
                'name': 'E2E Espresso', 'original_price': 25000,
                'count': 10, 'category': self.category.pk, 'available': True,
            }).json()
        self.product = Product.objects.get(pk=product['pk'])
        self.request(self.manager, 'PUT', '/api/v1/menu/%s/product/add-remove/' % self.menu.pk,
                     json={'product': self.product.pk, 'action': 'ADD'})
        menu = self.request(self.customer, 'GET', reverse('category_based_menu_active', kwargs={
            'cafe_id': self.cafe.pk})).json()
        self.assertIn('E2E Espresso', str(menu))
        order = self.request(self.customer, 'POST',
                             '/api/v1/table/%s/products/bulk/post/' % self.table_token.token,
                             json={'table_products': [{'product': self.product.pk, 'count': quantity}],
                                   'description': 'HTTP sale regression'}).json()
        self.pbr = ProductBillRelation.objects.get(product=self.product, user_profile=self.buyer)
        self.join_id = order['pk']
        self.assertEqual(self.pbr.count, quantity)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, 10 - quantity)
        self.assertEqual(self.pbr.remaining_amount, 25000 * quantity)

    def checkout(self, use_wallet=False):
        wallet_balance = self.buyer.wallet.balance
        session = self.request(self.customer, 'POST', reverse('pbr_session_create'),
                               expected=201, json={
                                   'payments': [{'pbr': self.pbr.pk, 'amount': self.pbr.remaining_amount}],
                                   'use_wallet': use_wallet,
                               }).json()
        self.invoice = Invoice.objects.get(uuid=session['invoice_uuid'])
        self.assertEqual(self.invoice.status, InvoiceConsts.CREATED)
        self.assertEqual(self.buyer.wallet.balance, wallet_balance)
        return self.prepare()

    def prepare(self):
        result = self.request(self.customer, 'GET',
                              '/api/v1/payment/make/%s/' % self.invoice.uuid).json()
        self.assertIs(result['mock'], True)
        self.checkout_url = result['redirect_to']
        self.invoice.refresh_from_db()
        page = self.request(self.gateway, 'GET', self.checkout_url)
        self.assertIn('تأیید پرداخت آزمایشی', page.text)
        self.assertIn('پول واقعی جابه‌جا نمی‌شود', page.text)
        self.assertIn('lang="fa" dir="rtl"', page.text)
        self.assertEqual(page.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(self.invoice.status, InvoiceConsts.IN_PAYMENT)
        return self.checkout_url

    def decide(self, decision='approve', expected=302, token=None):
        return self.request(self.gateway, 'POST', self.checkout_url, expected=expected, data={
            'decision': decision, 'token': self.invoice.token if token is None else token,
            'csrfmiddlewaretoken': self.gateway.cookies['csrftoken'],
        })

    def assert_result(self, response, status):
        location = urlsplit(response.headers['Location'])
        self.assertEqual(location.netloc, 'localhost:3000')
        self.assertEqual(location.path, '/paymentResult/')
        query = parse_qs(location.query)
        self.assertEqual(query['status'], [str(status)])
        self.assertEqual(query['mock'], ['true'])
        self.assertEqual(query['uuid'], [str(self.invoice.uuid)])

    def assert_paid_sale(self):
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceConsts.PAYED)
        self.assertTrue(self.invoice.transId.startswith('MOCK-'))
        self.assertEqual(self.pbr.remaining_amount, 0)
        self.assertEqual(self.cafe.wallet.balance, self.pbr.total_amount)
        self.assertEqual(self.buyer.wallet.balance, 0)
        self.assertEqual(self.pbr.invoices.filter(type=InvoiceConsts.DEPOSIT).count(), 1)
        report = self.request(self.manager, 'GET', reverse('join_simple_info', kwargs={
            'join_id': self.join_id})).json()
        self.assertEqual(report['payment_info']['net_amount'], 0)

    def test_new_product_menu_order_approve_receipt_and_sale(self):
        self.create_order()
        self.checkout()
        self.assert_result(self.decide(), 200)
        self.assert_paid_sale()
        self.notifications.assert_called_once()

    def test_decline_leaves_sale_unpaid_and_retry_uses_new_token(self):
        self.create_order()
        self.checkout()
        old_url, old_token = self.checkout_url, self.invoice.token
        self.assert_result(self.decide('decline'), 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceConsts.REJECTED)
        self.assertEqual(self.pbr.remaining_amount, 50000)
        self.assertEqual(self.cafe.wallet.balance, 0)
        self.assertEqual(self.buyer.wallet.balance, 0)
        self.notifications.assert_not_called()
        self.prepare()
        self.assertNotEqual(self.invoice.token, old_token)
        self.request(self.gateway, 'GET', old_url, expected=404)
        self.assert_result(self.decide(), 200)
        self.assert_paid_sale()

    def test_replayed_approval_decline_and_callback_do_not_duplicate_sale(self):
        self.create_order()
        self.checkout()
        self.decide()
        invoice_count = Invoice.objects.count()
        self.assert_result(self.decide(), 200)
        self.assert_result(self.decide('decline'), 200)
        self.assert_result(self.request(self.gateway, 'GET', self.checkout_url, expected=302), 200)
        self.assert_result(self.request(self.gateway, 'GET', reverse('payment_verify', kwargs={
            'invoice_uuid': self.invoice.uuid, 'pg': 'LOCAL'}), expected=302), 200)
        self.assertEqual(Invoice.objects.count(), invoice_count)
        self.assert_paid_sale()
        self.notifications.assert_called_once()

    def test_callback_does_not_approve_pending_invoice(self):
        self.create_order()
        self.checkout()
        response = self.request(self.gateway, 'GET', reverse('payment_verify', kwargs={
            'invoice_uuid': self.invoice.uuid, 'pg': 'LOCAL'}), expected=302)
        self.assert_result(response, 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceConsts.IN_PAYMENT)
        self.assertEqual(self.cafe.wallet.balance, 0)

    def test_checkout_requires_valid_token_and_csrf(self):
        self.create_order()
        self.checkout()
        self.decide(token='invalid', expected=404)
        self.request(self.gateway, 'POST', self.checkout_url, expected=403,
                     data={'decision': 'approve', 'token': self.invoice.token})
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceConsts.IN_PAYMENT)
        self.assertEqual(self.buyer.wallet.balance, 0)
        self.assertEqual(self.cafe.wallet.balance, 0)

    def test_expired_checkout_cannot_settle_and_can_be_restarted(self):
        self.create_order()
        self.checkout()
        Invoice.objects.filter(pk=self.invoice.pk).update(
            last_payment_timestamp=timezone.now() - timedelta(minutes=31))
        self.request(self.gateway, 'GET', self.checkout_url, expected=410)
        self.decide(expected=410)
        self.prepare()
        self.decide()
        self.assert_paid_sale()

    def test_failed_settlement_rolls_back_credit_and_transfers(self):
        self.create_order()
        self.checkout()
        # Simulate a price change after checkout, causing amount reconciliation to fail.
        ProductBillRelation.objects.filter(pk=self.pbr.pk).update(original_price=10000)
        invoice_count = Invoice.objects.count()
        self.decide(expected=409)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceConsts.IN_PAYMENT)
        self.assertEqual(self.invoice.transId, '')
        self.assertEqual(Invoice.objects.count(), invoice_count)
        self.assertEqual(self.cafe.wallet.balance, 0)
        self.assertEqual(self.buyer.wallet.balance, 0)
        self.notifications.assert_not_called()
        ProductBillRelation.objects.filter(pk=self.pbr.pk).update(original_price=25000)
        self.decide()
        self.assert_paid_sale()

    def test_gateway_requires_both_local_flags(self):
        self.create_order()
        self.checkout()
        for flag in ('CAFEPAY_LOCAL_RECOVERY', 'CAFEPAY_MOCK_PAYMENTS'):
            with self.settings(**{flag: False}):
                self.request(self.gateway, 'GET', self.checkout_url, expected=404)
                self.decide(expected=404)
                self.request(self.customer, 'GET',
                             '/api/v1/payment/make/%s/' % self.invoice.uuid, expected=404)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceConsts.IN_PAYMENT)

    def test_wallet_charge_approval_is_idempotent(self):
        self.invoice = self.buyer.wallet.deposit(amount=25000, tag=InvoiceConsts.CHARGE_WALLET)
        self.prepare()
        self.assert_result(self.decide(), 200)
        self.assert_result(self.decide(), 200)
        self.assertEqual(self.buyer.wallet.balance, 25000)
        self.notifications.assert_not_called()

    def test_partial_wallet_payment_settles_order_once(self):
        self.create_order()
        self.buyer.wallet.deposit(amount=25000, tag=InvoiceConsts.CHARGE_WALLET,
                                  status=InvoiceConsts.PAYED)
        self.checkout(use_wallet=True)
        self.assertEqual(self.invoice.amount, 25000)
        self.assertFalse(self.invoice.fake)
        self.assert_result(self.decide(), 200)
        self.assert_paid_sale()
        invoice_count = Invoice.objects.count()
        self.assert_result(self.decide(), 200)
        self.assertEqual(Invoice.objects.count(), invoice_count)
        self.assert_paid_sale()
        self.notifications.assert_called_once()

    def test_full_wallet_payment_settles_order_without_extra_credit(self):
        self.create_order()
        self.buyer.wallet.deposit(amount=50000, tag=InvoiceConsts.CHARGE_WALLET,
                                  status=InvoiceConsts.PAYED)
        self.checkout(use_wallet=True)
        self.assertEqual(self.invoice.amount, 0)
        self.assertTrue(self.invoice.fake)
        self.assert_result(self.decide(), 200)
        self.assert_paid_sale()
        invoice_count = Invoice.objects.count()
        self.assert_result(self.decide(), 200)
        self.assertEqual(Invoice.objects.count(), invoice_count)
        self.assert_paid_sale()
        self.notifications.assert_called_once()

    def test_customer_cannot_create_product(self):
        self.request(self.customer, 'POST', reverse('product_create', kwargs={
            'cafe_id': self.cafe.pk}), expected=403,
            json={'name': 'Unauthorized', 'original_price': 25000, 'category': self.category.pk})
        self.assertFalse(Product.objects.exists())

    def test_insufficient_inventory_does_not_create_sale(self):
        self.create_order()
        self.request(self.customer, 'POST',
                     '/api/v1/table/%s/products/bulk/post/' % self.table_token.token,
                     expected=400, json={'table_products': [{'product': self.product.pk, 'count': 9}]})
        self.product.refresh_from_db()
        self.pbr.refresh_from_db()
        self.assertEqual(self.product.count, 8)
        self.assertEqual(self.pbr.count, 2)
