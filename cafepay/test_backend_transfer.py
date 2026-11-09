"""Transferred bills retain their orders, ownership, and payment destination."""
from django.test import TestCase, override_settings
from django.urls import reverse

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.models import Bill, Invoice, PBRPayment, PBRPaymentSession, Table, TableJoin
from cafepay.test_backend_support import BackendFixtures


@override_settings(CAFEPAY_LOCAL_RECOVERY=True, CAFEPAY_MOCK_PAYMENTS=True)
class TransferredOrderTests(BackendFixtures, TestCase):
    def checkout(self):
        return self.client.post('/api/v1/pbr/session/create/', {
            'payments': [{'pbr': self.pbr.pk, 'amount': 10000}], 'use_wallet': False,
        }, format='json')

    def test_transferred_products_remain_payable_at_the_destination(self):
        target = Table.objects.create(cafe=self.cafe, number='Target')
        self.table.transfer(target)
        self.bill.refresh_from_db()
        self.assertIsNone(self.bill.join_id)
        self.assertEqual(list(target.active_join.all_products), [self.pbr])
        self.assertEqual(list(target.active_bill.all_products), [self.pbr])
        self.assertEqual(list(self.bill.all_products), [self.pbr])
        self.assertEqual(self.bill.current_owner.table_id, target.pk)
        self.authenticate(self.customer)
        response = self.checkout()
        self.assertEqual(response.status_code, 201, response.data)
        session = PBRPaymentSession.objects.get(pk=response.data['pk'])
        self.assertEqual(session.invoice.extra.pk, target.pk)

    def test_repeated_transfers_and_separation_do_not_recurse_or_duplicate_orders(self):
        second = Table.objects.create(cafe=self.cafe, number='Second')
        third = Table.objects.create(cafe=self.cafe, number='Third')
        fourth = Table.objects.create(cafe=self.cafe, number='Fourth')
        self.table.transfer(second)
        second.transfer(third)
        third.make_join(fourth)
        third.separate()
        join = fourth.active_join
        with self.assertNumQueries(1):
            self.assertEqual(list(join.all_products), [self.pbr])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.current_owner.table_id, fourth.pk)
        self.authenticate(self.customer)
        self.assertEqual(self.checkout().status_code, 201)
        join.force_close = True
        join.save()
        self.assertEqual(self.checkout().status_code, 400)

    def test_transferred_customer_access_does_not_grant_access_to_unrelated_users(self):
        target = Table.objects.create(cafe=self.cafe, number='Target')
        self.table.transfer(target)
        url = reverse('join_simple_info', kwargs={'join_id': target.active_join.pk})
        self.authenticate(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.authenticate(self.other_staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.authenticate(self.customer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post('/api/v1/cafe/%s/pbr/payment/method/' % self.cafe.pk, {
            'pbr_payment_methods': [{'pbr': self.pbr.pk, 'preferred_payment_method': InvoiceConsts.CASH}],
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

    def test_refund_query_includes_transferred_payments_once(self):
        target = Table.objects.create(cafe=self.cafe, number='Target')
        self.table.transfer(target)
        invoice = Invoice.objects.create(wallet=self.customer.wallet, amount=20000,
            status=InvoiceConsts.PAYED, method=InvoiceConsts.ONLINE, type=InvoiceConsts.DEPOSIT)
        session = PBRPaymentSession.objects.create(user_profile=self.customer, invoice=invoice)
        PBRPayment.objects.create(session=session, pbr=self.pbr, amount=20000)
        join = target.active_join
        with self.assertNumQueries(1):
            self.assertEqual(list(join.get_all_online_payed_invoices()), [invoice])

    def test_corrupt_cross_cafe_links_do_not_expose_or_charge_foreign_orders(self):
        target = Table.objects.create(cafe=self.other_cafe, number='Foreign')
        owner = target.get_or_create_bill()
        owner.pre_bill.add(self.bill)
        self.bill.join = None
        self.bill.save()
        self.assertFalse(target.active_join.all_products.exists())
        self.assertIsNone(self.bill.current_owner)
        self.authenticate(self.customer)
        self.assertEqual(self.checkout().status_code, 400)
