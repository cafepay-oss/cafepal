"""Cancellation returns inventory once and preserves concurrent order changes."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from cafepay.api_v1.views.JoinViews import CancelJoinView
from cafepay.models import Product, ProductBillRelation, Table
from cafepay.test_backend_support import BackendFixtures


class CancellationConcurrencyTests(BackendFixtures, TransactionTestCase):
    def in_connection(self, operation):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '3s'")
            return operation()
        finally:
            close_old_connections()

    def cancel_join(self, join_id):
        client = APIClient()
        client.force_authenticate(self.staff.django_user)
        response = client.put('/api/v1/join/%s/cancel/' % join_id, {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.status_code

    def test_overlapping_cancellations_with_stale_pbr_return_stock_once(self):
        stale_ready = Event()
        first_finished = Event()

        def first():
            self.assertTrue(stale_ready.wait(timeout=10))
            try:
                CancelJoinView.cancel_pbr(ProductBillRelation.objects.get(pk=self.pbr.pk))
            finally:
                first_finished.set()

        def stale_request():
            stale = ProductBillRelation.objects.get(pk=self.pbr.pk)
            stale_ready.set()
            self.assertTrue(first_finished.wait(timeout=10))
            CancelJoinView.cancel_pbr(stale)

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(self.in_connection, operation) for operation in (first, stale_request)]
            for future in futures:
                future.result(timeout=20)
        self.product.refresh_from_db()
        self.pbr.refresh_from_db()
        self.assertEqual(self.product.count, 12)
        self.assertEqual(self.pbr.status, ProductBillRelation.CANCELED)

    def test_simultaneous_cancel_requests_close_join_and_return_stock_once(self):
        ready = Barrier(2)
        def cancel():
            ready.wait(timeout=10)
            return self.cancel_join(self.join.pk)
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(self.in_connection, cancel) for _ in range(2)]
            self.assertEqual([future.result(timeout=20) for future in futures], [200, 200])
        self.product.refresh_from_db()
        self.join.refresh_from_db()
        self.assertEqual(self.product.count, 12)
        self.assertTrue(self.join.force_close)

    def test_cancellation_preserves_an_order_added_after_its_initial_read(self):
        stale_ready = Event()
        order_finished = Event()
        other_table = Table.objects.create(cafe=self.cafe, number='Other order')

        def add_order():
            self.assertTrue(stale_ready.wait(timeout=10))
            try:
                other_table.add_product(self.product, self.customer)
            finally:
                order_finished.set()

        def stale_cancel():
            stale = ProductBillRelation.objects.select_related('product').get(pk=self.pbr.pk)
            stale_ready.set()
            self.assertTrue(order_finished.wait(timeout=10))
            CancelJoinView.cancel_pbr(stale)

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(self.in_connection, operation) for operation in (add_order, stale_cancel)]
            for future in futures:
                future.result(timeout=20)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, 11)
        self.assertEqual(other_table.active_bill.bill_pbrs.get().count, 1)

    def test_cancel_destination_returns_transferred_items_once(self):
        destination = Table.objects.create(cafe=self.cafe, number='Destination')
        self.table.transfer(destination)
        destination_join = destination.active_join
        self.cancel_join(destination_join.pk)
        self.cancel_join(destination_join.pk)
        self.product.refresh_from_db()
        self.pbr.refresh_from_db()
        self.assertEqual(self.product.count, 12)
        self.assertEqual(self.pbr.status, ProductBillRelation.CANCELED)

    def test_failed_cancellation_rolls_back_stock_and_status_changes(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        other = ProductBillRelation.objects.create(
            bill=self.bill, product=self.product, user_profile=self.customer,
            count=3, original_price=10000, discount=0)
        cancel_locked = CancelJoinView._cancel_locked_pbr
        def fail_second(pbr):
            if pbr.pk == other.pk:
                raise RuntimeError('Stop isolated cancellation test')
            cancel_locked(pbr)
        with patch.object(CancelJoinView, '_cancel_locked_pbr', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                CancelJoinView().perform_update(SimpleNamespace(instance=self.join))
        self.product.refresh_from_db()
        self.pbr.refresh_from_db()
        self.join.refresh_from_db()
        self.assertEqual(self.product.count, 10)
        self.assertEqual(self.pbr.status, ProductBillRelation.PENDING)
        self.assertFalse(self.join.force_close)

    def test_cancellation_preserves_join_metadata_changed_after_initial_read(self):
        from types import SimpleNamespace
        from cafepay.models import TableJoin
        TableJoin.objects.filter(pk=self.join.pk).update(description='Updated description')
        CancelJoinView().perform_update(SimpleNamespace(instance=self.join))
        self.join.refresh_from_db()
        self.assertEqual(self.join.description, 'Updated description')
        self.assertTrue(self.join.force_close)
