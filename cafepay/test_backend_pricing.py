"""Menu and historical order prices use the same exact currency arithmetic."""
from django.test import SimpleTestCase

from cafepay.models import Product, ProductBillRelation


class DiscountArithmeticTests(SimpleTestCase):
    def test_menu_and_order_prices_match_for_every_discount_percentage(self):
        for price in (1, 99, 100, 1000, 25000, 2147483647):
            for discount in range(101):
                with self.subTest(price=price, discount=discount):
                    expected = price * (100 - discount) // 100
                    product = Product(original_price=price, discount=discount)
                    order = ProductBillRelation(original_price=price, discount=discount, count=3)
                    self.assertEqual(product.price, expected)
                    self.assertEqual(order.unit_amount, expected)
                    self.assertEqual(order.total_amount, expected * 3)
