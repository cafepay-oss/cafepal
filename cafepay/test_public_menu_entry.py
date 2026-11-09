"""Anonymous menu links expose public metadata and defer order allocation to login."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.models import (Bill, CafeWallet, Invoice, ProductBillRelation,
                           ScannedTable, Table, TableJoin, TableToken, Wallet)
from cafepay.test_backend_support import BackendFixtures


class PublicMenuEntryTests(BackendFixtures, TestCase):
    def entry_url(self, token=None):
        return reverse('table_token_cafe_info', kwargs={
            'table_token': (token or self.table_token).token})

    def allocation_counts(self):
        return [model.objects.count() for model in (
            Table, TableToken, TableJoin, Bill, ProductBillRelation,
            ScannedTable, CafeWallet, Wallet, Invoice)]

    def test_anonymous_public_links_return_metadata_without_private_data_or_writes(self):
        # Existing orders, staff items, and cafe credit must not appear in this response.
        self.pbr.is_staff = True
        self.pbr.save(update_fields=['is_staff'])
        self.cafe.has_first_time_offer = True
        self.cafe.first_time_offer_amount = 10000
        self.cafe.save()
        credit = CafeWallet.objects.create(cafe=self.cafe, user_profile=self.customer, wallet=Wallet.objects.create())
        credit.wallet.deposit(amount=5000, status=InvoiceConsts.PAYED)
        for token_type in (TableToken.MENU_ONLY, TableToken.SELF_PICKUP):
            self.table_token.type = token_type
            self.table_token.has_delivery = True
            self.table_token.save()
            before = self.allocation_counts()
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.entry_url())
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(set(response.data), {'token', 'cafe', 'type', 'has_delivery',
                'get_type_display', 'menu_only', 'pk', 'table', 'orders',
                'has_staff_order', 'my_credit_in_cafe'})
            self.assertEqual(response.data['token'], self.table_token.token)
            self.assertEqual(response.data['type'], token_type)
            self.assertTrue(response.data['has_delivery'])
            self.assertEqual(response.data['menu_only'], token_type == TableToken.MENU_ONLY)
            self.assertEqual(response.data['cafe']['pk'], self.cafe.pk)
            self.assertIsNone(response.data['pk'])
            self.assertEqual(response.data['table'], {'pk': None, 'uuid': None, 'number': ''})
            self.assertIsNone(response.data['orders'])
            self.assertFalse(response.data['has_staff_order'])
            self.assertEqual(response.data['my_credit_in_cafe'], 0)
            self.assertEqual(self.allocation_counts(), before)
            writes = [query['sql'] for query in queries
                      if query['sql'].lstrip().split(None, 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE')]
            self.assertEqual(writes, [])

    def test_anonymous_normal_and_payment_only_links_still_require_login(self):
        for token_type in (TableToken.NORMAL, TableToken.PAYMENT_ONLY):
            self.table_token.type = token_type
            self.table_token.save()
            before = self.allocation_counts()
            response = self.client.get(self.entry_url())
            self.assertIn(response.status_code, (401, 403), response.data)
            self.assertEqual(self.allocation_counts(), before)

    def test_inactive_public_link_does_not_return_cafe_data(self):
        self.table_token.type = TableToken.SELF_PICKUP
        self.table_token.status = TableToken.INACTIVE
        self.table_token.save()
        before = self.allocation_counts()
        response = self.client.get(self.entry_url())
        self.assertEqual(response.status_code, 404, response.data)
        self.assertNotIn('cafe', response.data)
        self.assertEqual(self.allocation_counts(), before)

    def test_login_allocates_preorder_and_preserves_existing_order_submission(self):
        self.table_token.type = TableToken.SELF_PICKUP
        self.table_token.save()
        public = self.client.get(self.entry_url())
        self.assertEqual(public.status_code, 200, public.data)
        self.authenticate(self.customer)
        response = self.client.get(self.entry_url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response.data['token'], self.table_token.token)
        self.assertIsNotNone(response.data['table']['pk'])
        self.assertIsNotNone(response.data['table']['uuid'])
        allocated_token = response.data['token']
        order = self.client.post('/api/v1/table/%s/products/change/' % allocated_token,
            {'add': [{'product': self.product.pk, 'count': 1}]}, format='json')
        self.assertEqual(order.status_code, 200, order.data)
        pbr = ProductBillRelation.objects.get(bill__table_id=response.data['table']['pk'])
        self.assertEqual(pbr.user_profile_id, self.customer.private_id)
        self.assertEqual(pbr.count, 1)
        self.assertTrue(ScannedTable.objects.filter(user_profile=self.customer,
                                                   bill__table_id=response.data['table']['pk']).exists())
        reopened = self.client.get(self.entry_url())
        self.assertEqual(reopened.status_code, 200, reopened.data)
        self.assertEqual(reopened.data['table']['pk'], response.data['table']['pk'])
        self.assertEqual(reopened.data['orders']['pk'], order.data['pk'])

    def test_anonymous_public_link_cannot_submit_an_order(self):
        self.table_token.type = TableToken.SELF_PICKUP
        self.table_token.save()
        before = self.allocation_counts()
        response = self.client.post('/api/v1/table/%s/products/change/' % self.table_token.token,
            {'add': [{'product': self.product.pk, 'count': 1}]}, format='json')
        self.assertIn(response.status_code, (401, 403), response.data)
        self.assertEqual(self.allocation_counts(), before)
