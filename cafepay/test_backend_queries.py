"""Query regressions for cafe rankings and bounded order updates."""
from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.views.ShopViews import CafeListView
from cafepay.models import Cafe, Invoice, Wallet
from cafepay.test_backend_support import BackendFixtures


class CafeRankingQueryTests(BackendFixtures, TestCase):
    def test_cafe_ranking_uses_one_query_and_preserves_totals(self):
        for number in range(48):
            Cafe.objects.create(name='Cafe %s' % number, address='Query fixture', wallet=Wallet.objects.create())
        for amount in (100, 100):
            Invoice.objects.create(wallet=self.cafe.wallet, amount=amount, type=InvoiceConsts.DEPOSIT)
        Invoice.objects.create(wallet=self.other_cafe.wallet, amount=150, type=InvoiceConsts.DEPOSIT)
        Invoice.objects.create(wallet=self.other_cafe.wallet, amount=900, type=InvoiceConsts.WITHDRAW)
        with self.assertNumQueries(1):
            cafes = list(CafeListView().get_queryset())
        self.assertEqual(len(cafes), 50)
        self.assertEqual([cafe.pk for cafe in cafes[-2:]], [self.other_cafe.pk, self.cafe.pk])
        self.assertEqual(cafes[-1].deposit_total, 200)
        with self.assertNumQueries(1):
            first_page = list(CafeListView().get_queryset()[:10])
        self.assertEqual(len(first_page), 10)
        self.assertTrue(all(cafe.deposit_total == 0 for cafe in first_page))

    def test_order_quantity_does_not_multiply_mutation_queries(self):
        from cafepay.api_v1.views.TableViews import apply_table_product_changes
        from django.utils import timezone
        query_counts = []
        for quantity in (1, 5):
            with CaptureQueriesContext(connection) as queries:
                apply_table_product_changes(self.table, {'add': [{
                    'product': self.product, 'count': quantity, 'pickup_time': timezone.now(),
                }]}, self.customer)
            query_counts.append(len(queries))
        self.assertEqual(query_counts[0], query_counts[1])
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, 4)
