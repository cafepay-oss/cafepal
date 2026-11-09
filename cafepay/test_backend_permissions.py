"""Order access must remain within cafe staff and bill participants."""
from django.test import TestCase

from cafepay.models import ProductBillRelation
from cafepay.test_backend_support import BackendFixtures


class OrderAccessTests(BackendFixtures, TestCase):
    def test_private_order_reads_reject_anonymous_and_unrelated_users(self):
        urls = [
            '/api/v1/join/simple/%s/' % self.join.pk,
            '/api/v1/join/detailed/%s/' % self.join.pk,
            '/api/v1/bill/simple/%s/' % self.bill.pk,
            '/api/v1/bill/detailed/%s/' % self.bill.pk,
        ]
        for profile in (None, self.outsider, self.other_staff):
            self.authenticate(profile)
            for url in urls:
                with self.subTest(profile=profile, url=url):
                    self.assertIn(self.client.get(url).status_code, (401, 403))
        self.authenticate(self.staff)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.authenticate(self.customer)
        for url in urls:
            expected = 403 if '/detailed/' in url else 200
            self.assertEqual(self.client.get(url).status_code, expected, url)

    def test_kitchen_updates_require_staff_for_the_order_cafe(self):
        for action in ('send-to-kitchen', 'accept'):
            url = '/api/v1/pbr/%s/%s/' % (self.pbr.pk, action)
            for profile in (None, self.customer, self.other_staff):
                self.authenticate(profile)
                self.assertIn(self.client.patch(url, {}, format='json').status_code, (401, 403))
                self.pbr.refresh_from_db()
                self.assertEqual(self.pbr.status, ProductBillRelation.PENDING)
        self.authenticate(self.staff)
        response = self.client.patch('/api/v1/pbr/%s/accept/' % self.pbr.pk,
                                     {'is_accepted': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.status, ProductBillRelation.ACCEPTED)

    def test_pbr_deletion_checks_object_permissions(self):
        url = '/api/v1/pbr/%s/update/' % self.pbr.pk
        for profile in (None, self.outsider, self.customer, self.other_staff):
            self.authenticate(profile)
            response = self.client.delete(url)
            self.assertIn(response.status_code, (401, 403), response.data)
            self.pbr.refresh_from_db()
            self.product.refresh_from_db()
            self.assertEqual(self.pbr.count, 2)
            self.assertEqual(self.product.count, 10)
        self.authenticate(self.staff)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.count, 1)

    def test_bulk_delivery_prices_require_same_cafe_staff(self):
        from cafepay.models import City, Region, CafeRegionPrice
        city = City.objects.create(name='Test city')
        region = Region.objects.create(name='Test region', city=city)
        url = '/api/v1/cafe/%s/region-price/bulk/create/' % self.cafe.pk
        payload = {'region_prices': [{'region': region.pk, 'price': 1000}]}
        for profile in (None, self.customer, self.other_staff):
            self.authenticate(profile)
            self.assertIn(self.client.post(url, payload, format='json').status_code, (401, 403))
            self.assertFalse(CafeRegionPrice.objects.exists())
        self.authenticate(self.staff)
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(CafeRegionPrice.objects.get().price, 1000)

    def test_payment_methods_validate_scope_and_empty_batches(self):
        from cafepay.api_v1.consts import InvoiceConsts
        url = '/api/v1/cafe/%s/pbr/payment/method/' % self.cafe.pk
        payload = {'pbr_payment_methods': [
            {'pbr': self.pbr.pk, 'preferred_payment_method': InvoiceConsts.CASH}]}
        self.authenticate(None)
        self.assertIn(self.client.post(url, payload, format='json').status_code, (401, 403))
        for profile in (self.outsider, self.other_staff):
            self.authenticate(profile)
            self.assertEqual(self.client.post(url, payload, format='json').status_code, 400)
        self.authenticate(self.customer)
        self.assertEqual(self.client.post(url, {'pbr_payment_methods': []}, format='json').status_code, 400)
        wrong_cafe = '/api/v1/cafe/%s/pbr/payment/method/' % self.other_cafe.pk
        self.assertEqual(self.client.post(wrong_cafe, payload, format='json').status_code, 400)
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.preferred_payment_method, InvoiceConsts.ONLINE)
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.preferred_payment_method, InvoiceConsts.CASH)

    def test_table_edit_permissions_and_partial_update(self):
        url = '/api/v1/table/%s/' % self.table.pk
        for profile in (None, self.customer, self.other_staff):
            self.authenticate(profile)
            self.assertIn(self.client.patch(url, {'number': 'Changed'}, format='json').status_code, (401, 403))
        self.staff.django_user.is_superuser = True
        self.staff.django_user.save()
        self.authenticate(self.staff)
        response = self.client.patch(url, {'number': 'Changed'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.table.refresh_from_db()
        self.assertEqual(self.table.number, 'Changed')

    def test_product_image_creation_checks_product_permission(self):
        url = '/api/v1/product/%s/image/add/' % self.product.pk
        for profile in (None, self.customer, self.other_staff):
            self.authenticate(profile)
            # Permissions must fail before image-file validation.
            self.assertIn(self.client.post(url, {}, format='json').status_code, (401, 403))

    def test_nested_product_and_category_relations_stay_in_cafe(self):
        from cafepay.models import Menu, CharacterField
        from cafepay.api_v1.consts import CharacterFieldConsts
        from cafepay.api_v1.serializers.ProductSerializers import ProductCUSerializer
        from cafepay.api_v1.serializers.CategorySerializers import CategoryRUDSerializer, GroupRUDSerializer
        other = self.make_product(self.other_cafe, self.other_staff)
        foreign_menu = Menu.objects.create(cafe=self.other_cafe, staff=self.other_staff, name='Other menu')
        for payload in ({'category': other.category.pk}, {'count': -1}):
            serializer = ProductCUSerializer(self.product, data=payload, partial=True)
            self.assertFalse(serializer.is_valid())
        serializer = CategoryRUDSerializer(self.product.category, data={'menu': foreign_menu.pk}, partial=True)
        self.assertFalse(serializer.is_valid())
        group = CharacterField.objects.create(cafe=self.cafe, staff=self.staff, title='Group',
                                               type=CharacterFieldConsts.GROUP)
        serializer = GroupRUDSerializer(group, data={'group_products': [other.pk]}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.authenticate(self.staff)
        response = self.client.put('/api/v1/cafe/%s/categories/set/order/' % self.cafe.pk,
            {'category_orders': [{'category': other.category.pk, 'order': 99}]}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        other.category.refresh_from_db()
        self.assertEqual(other.category.order, 0)
