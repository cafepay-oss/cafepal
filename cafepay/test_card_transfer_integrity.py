"""Keep receipt orders intact through table operations and receipt rejection."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import APIException

from cafepay.api_v1.helpers import APIBadRequest
from cafepay.api_v1.modules.card_transfer import start_transfer, submit_receipt, review_transfer
from cafepay.api_v1.serializers.JoinSerializers import TableJoinBaseSerializer
from cafepay.models import (Bill, CafeRegionPrice, CardTransfer, City, ProductBillRelation,
                           Region, Table, UserProfileAddress)
from cafepay.test_card_transfers import ReceiptFixtures, receipt_file


class CardTransferIntegrityTests(ReceiptFixtures, TestCase):
    def test_order_summary_keeps_the_quoted_delivery_fee(self):
        city = City.objects.create(name='Test')
        region = Region.objects.create(name='Local', city=city)
        delivery = CafeRegionPrice.objects.create(cafe=self.cafe, region=region, price=5000)
        self.join.address = UserProfileAddress.objects.create(
            region=region, user_profile=self.customer, address='Test')
        self.join.include_delivery_fee = True
        self.join.save()
        transfer = start_transfer(self.join.pk, self.customer)
        submit_receipt(transfer, self.customer, receipt_file())
        delivery.price = 8000
        delivery.save()
        summary = TableJoinBaseSerializer(self.join).data['card_transfer']
        self.assertEqual(summary['amount'], 25000)
        self.assertEqual(summary['delivery_fee'], 5000)

    def test_receipt_blocks_movement_from_and_into_its_order(self):
        other_join = self.new_order()
        other_table = other_join.bills.get().table
        transfer = start_transfer(self.join.pk, self.customer)
        for state in (CardTransfer.DRAFT, CardTransfer.SUBMITTED,
                      CardTransfer.REJECTED, CardTransfer.CONFIRMED):
            # Exercise every protected state against both directions of each route.
            CardTransfer.objects.filter(pk=transfer.pk).update(status=state)
            self.authenticate(self.staff)
            for operation in ('join', 'transfer'):
                for source, target in ((self.table, other_table), (other_table, self.table)):
                    with self.subTest(state=state, operation=operation, source=source.pk):
                        response = self.client.patch('/api/v1/table/%s/%s/%s/' % (
                            source.pk, operation, target.pk), {}, format='json')
                        self.assertEqual(response.status_code, 400, response.data)
            self.bill.refresh_from_db()
            self.assertEqual(self.bill.join_id, self.join.pk)
            self.assertEqual(other_join.bills.get().table_id, other_table.pk)
            self.assertFalse(self.bill.pre_bill.exists())

    def test_receipt_blocks_separating_its_tables(self):
        other_table = Table.objects.create(cafe=self.cafe, number='Second receipt table')
        other_bill = Bill.objects.create(table=other_table, join=self.join)
        start_transfer(self.join.pk, self.customer)
        self.authenticate(self.staff)
        response = self.client.patch('/api/v1/table/%s/separate/' % self.table.pk, {}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(set(self.join.bills.values_list('pk', flat=True)), {self.bill.pk, other_bill.pk})

    def test_rejected_receipt_preserves_prepared_basket_and_allows_replacement(self):
        transfer = start_transfer(self.join.pk, self.customer)
        transfer = submit_receipt(transfer, self.customer, receipt_file())
        self.pbr.status = ProductBillRelation.KITCHEN
        self.pbr.save(update_fields=['status'])
        review_transfer(transfer, self.staff, 'reject', 'Please provide the correct receipt')
        for change in (self.table.add_product, self.table.remove_product):
            with self.assertRaises(APIBadRequest):
                change(self.product, self.customer)
        for path, data in [('user-profile-address', {'user_profile_address': None}),
                           ('include-delivery-fee', {'include_delivery_fee': True})]:
            response = self.client.patch('/api/v1/join/%s/set/%s/' % (self.join.pk, path), data, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        replacement = start_transfer(self.join.pk, self.customer)
        self.assertEqual(replacement.amount, transfer.amount)
        submit_receipt(replacement, self.customer, receipt_file('green'))
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.status, ProductBillRelation.KITCHEN)
        self.assertEqual(self.pbr.count, 2)


class ConcurrentCardTransferMovementTests(ReceiptFixtures, TransactionTestCase):
    def test_checkout_and_transfer_cannot_detach_a_receipt_order(self):
        other_table = self.new_order().bills.get().table
        ready = Barrier(2)

        def run(index):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                ready.wait(timeout=10)
                try:
                    if index == 0:
                        start_transfer(self.join.pk, self.customer)
                    else:
                        self.table.transfer(other_table)
                    return True
                except APIException:
                    return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            checkout_succeeded, movement_succeeded = list(workers.map(run, range(2)))
        self.assertNotEqual(checkout_succeeded, movement_succeeded)
        if checkout_succeeded:
            self.assertEqual(CardTransfer.objects.get().join_id, self.join.pk)
            self.assertEqual(self.join.all_products.count(), 1)
        else:
            self.assertFalse(CardTransfer.objects.exists())
            self.assertEqual(other_table.active_join.all_products.count(), 2)
