"""Order mutations must preserve inventory under concurrent requests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase

from cafepay.api_v1.helpers import APIBadRequest
from cafepay.models import Product, ProductBillRelation, Table
from cafepay.test_backend_support import BackendFixtures


class InventoryValidationTests(BackendFixtures, TestCase):
    def test_stock_validation_uses_locked_product_not_stale_instance(self):
        Product.objects.filter(pk=self.product.pk).update(count=0)
        with self.assertRaises(APIBadRequest):
            self.table.add_product(self.product, self.customer)
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, 0)
        self.assertEqual(ProductBillRelation.objects.get(pk=self.pbr.pk).count, 2)

    def test_ordering_rejects_unavailable_deleted_and_cross_cafe_products(self):
        other = self.make_product(self.other_cafe, self.other_staff)
        with self.assertRaises(APIBadRequest):
            self.table.add_product(other, self.customer)
        for changes in ({'available': False}, {'available': True, 'is_delete': True}):
            Product.objects.filter(pk=self.product.pk).update(**changes)
            with self.assertRaises(APIBadRequest):
                self.table.add_product(self.product, self.customer)
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, 10)


class InventoryConcurrencyTests(BackendFixtures, TransactionTestCase):
    def run_parallel(self, operation):
        ready = Barrier(2)

        def run(index):
            close_old_connections()
            try:
                # Both requests read stock before either acquires the mutation lock.
                product = Product.objects.get(pk=self.product.pk)
                ready.wait(timeout=10)
                try:
                    operation(index, product)
                    return 'ok'
                except APIBadRequest:
                    return 'rejected'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            return list(workers.map(run, range(2)))

    def test_last_unit_cannot_be_sold_twice_across_tables(self):
        Product.objects.filter(pk=self.product.pk).update(count=1)
        tables = [Table.objects.create(cafe=self.cafe, number=str(i + 2)) for i in range(2)]
        results = self.run_parallel(lambda i, product: tables[i].add_product(product, self.customer))
        self.assertCountEqual(results, ['ok', 'rejected'])
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, 0)
        self.assertEqual(ProductBillRelation.objects.exclude(pk=self.pbr.pk).count(), 1)

    def test_first_order_creates_one_active_bill(self):
        table = Table.objects.create(cafe=self.cafe, number='New table')
        self.assertEqual(self.run_parallel(lambda i, product: table.add_product(product, self.customer)),
                         ['ok', 'ok'])
        self.assertEqual(table.bills.count(), 1)
        self.assertEqual(table.active_bill.bill_pbrs.get().count, 2)
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, 8)

    def test_add_and_remove_preserve_stock(self):
        def change(index, product):
            if index:
                self.table.add_product(product, self.customer)
            else:
                self.table.remove_product(product, self.customer)
        self.assertEqual(self.run_parallel(change), ['ok', 'ok'])
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, 10)
        self.assertEqual(ProductBillRelation.objects.get(pk=self.pbr.pk).count, 2)


class OrderMutationAPITests(BackendFixtures, TestCase):
    def change_url(self):
        return '/api/v1/table/%s/products/change/' % self.table_token.token

    def test_mixed_edit_rolls_back_removal_when_addition_fails(self):
        self.authenticate(self.customer)
        response = self.client.post(self.change_url(), {
            'remove': [{'product': self.product.pk, 'count': 1}],
            'add': [{'product': self.product.pk, 'count': 50}],
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.pbr.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.pbr.count, 2)
        self.assertEqual(self.product.count, 10)
        response = self.client.post(self.change_url(), {
            'remove': [{'product': self.product.pk, 'count': 1}],
            'add': [{'product': self.product.pk, 'count': 2}],
            'description': 'سفارش آزمایشی',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.pbr.refresh_from_db()
        self.product.refresh_from_db()
        self.join.refresh_from_db()
        self.assertEqual(self.pbr.count, 3)
        self.assertEqual(self.product.count, 9)
        self.assertEqual(self.join.description, 'سفارش آزمایشی')

    def test_bulk_rejects_malformed_and_empty_input(self):
        self.authenticate(self.customer)
        url = '/api/v1/table/%s/products/bulk/post/' % self.table_token.token
        invalid = [{}, {'table_products': []}, {'table_products': [{'product': self.product.pk}]}]
        invalid += [{'table_products': [{'product': self.product.pk, 'count': value}]}
                    for value in (0, -1, 'invalid')]
        invalid.append({'table_products': [{'product': self.product.pk, 'count': 1,
                                            'pickup_time': 'not-a-date'}]})
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post(url, payload, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.count, 2)
        self.assertEqual(self.client.post(self.change_url(), {}, format='json').status_code, 400)

    def test_staff_mixed_edits_preserve_customer_ownership(self):
        url = '/api/v1/table/%s/products/change/staff/' % self.table.pk
        payload = {'remove': [{'product': self.product.pk, 'count': 1,
                               'user_profile': self.customer.pk, 'is_staff': False}],
                   'add': [{'product': self.product.pk, 'count': 1}]}
        self.authenticate(self.other_staff)
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 403)
        self.authenticate(self.staff)
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.count, 1)
        self.assertEqual(ProductBillRelation.objects.get(user_profile=self.staff, is_staff=True).count, 1)
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, 10)

    def test_single_item_endpoints_and_table_separation(self):
        from django.urls import reverse
        self.authenticate(self.customer)
        response = self.client.post(reverse('product_table', kwargs={
            'table_token': self.table_token.token, 'product_id': self.product.pk}))
        self.assertEqual(response.status_code, 200, response.data)
        self.authenticate(self.staff)
        response = self.client.post(reverse('pbr_update', kwargs={'pbr_id': self.pbr.pk}))
        self.assertEqual(response.status_code, 200, response.data)
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.count, 4)
        from cafepay.models import Bill
        other = Table.objects.create(cafe=self.cafe, number='Joined')
        Bill.objects.create(table=other, join=self.join)
        response = self.client.put(reverse('separate_table', kwargs={'table_id': self.table.pk}), {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(self.table.active_join)
        self.assertEqual(other.active_join.pk, self.join.pk)
        self.assertTrue(other.active_bill.pre_bill.filter(pk=self.bill.pk).exists())


class MenuTokenConcurrencyTests(BackendFixtures, TransactionTestCase):

    def test_concurrent_lazy_menu_provisioning_creates_one_table_and_token(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from cafepay.models import TableToken, Table
        ready = Barrier(2)
        before_tables = Table.objects.count()
        def token(_):
            close_old_connections()
            try:
                ready.wait(timeout=10)
                return self.cafe.get_or_create_token(TableToken.MENU_ONLY).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as workers:
            ids = list(workers.map(token, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(TableToken.objects.filter(cafe=self.cafe, type=TableToken.MENU_ONLY).count(), 1)
        self.assertEqual(Table.objects.count(), before_tables + 1)

