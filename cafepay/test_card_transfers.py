"""Receipt checkout and external-money reconciliation, with isolated products/files."""
import io
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from PIL import Image
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import APIBadRequest
from cafepay.api_v1.modules.card_transfer import start_transfer, submit_receipt, review_transfer
from cafepay.api_v1.serializers.JoinSerializers import TableJoinBaseSerializer
from cafepay.models import (Bill, Cafe, CafeRegionPrice, CardTransfer, City, Invoice, PBRPaymentSession,
                           Product, ProductBillRelation, Region, Table, TableJoin, UserProfileAddress)
from cafepay.test_backend_support import BackendFixtures


def receipt_file(color='blue'):
    image = io.BytesIO()
    Image.new('RGB', (40, 40), color).save(image, format='PNG')
    return SimpleUploadedFile('bank-receipt.png', image.getvalue(), content_type='image/png')


class ReceiptFixtures(BackendFixtures):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(PRIVATE_MEDIA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        notifier = patch('cafepay.api_v1.modules.card_transfer.notify_order')
        notifier.start()
        self.addCleanup(notifier.stop)
        self.cafe.card_transfer_enabled = True
        self.cafe.card_transfer_number = '6037991234567890'
        self.cafe.card_transfer_holder = 'Test store'
        self.cafe.save()
        self.authenticate(self.customer)

    def start(self, join=None):
        response = self.client.post('/api/v1/join/%s/card-transfer/' % (join or self.join).pk,
                                    {'amount': 1, 'destination_card': '0000000000000000'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def grant_permission(self, model, codename):
        # Legacy permissions come from restored data, not model migrations.
        permission, _ = Permission.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(model), codename=codename,
            defaults={'name': codename})
        self.staff.django_user.user_permissions.add(permission)
        self.staff.refresh_from_db()
        self.authenticate(self.staff)

    def upload(self, transfer, color='blue'):
        return self.client.post('/api/v1/card-transfers/%s/receipt/' % transfer['uuid'],
                                {'receipt': receipt_file(color)}, format='multipart')

    def review(self, transfer, decision='confirm', note=''):
        return self.client.post('/api/v1/card-transfers/%s/review/' % transfer['uuid'],
                                {'decision': decision, 'note': note}, format='json')

    def new_order(self):
        table = Table.objects.create(cafe=self.cafe, number='online', uuid=uuid4())
        join = TableJoin.objects.create(cafe=self.cafe)
        bill = Bill.objects.create(table=table, join=join)
        ProductBillRelation.objects.create(bill=bill, product=self.product, user_profile=self.customer,
                                           count=1, original_price=10000, discount=0)
        return join


class CardTransferTests(ReceiptFixtures, TestCase):
    def test_receipt_submits_order_without_crediting_ledger_and_retry_is_idempotent(self):
        transfer = self.start()
        self.assertEqual(transfer['amount'], 20000)
        self.assertEqual(transfer['destination_card'], self.cafe.card_transfer_number)
        self.assertEqual(self.start()['uuid'], transfer['uuid'])
        response = self.upload(transfer)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'submitted')
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.status, ProductBillRelation.ACCEPTED)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(PBRPaymentSession.objects.exists())
        self.assertEqual(self.pbr.remaining_amount, 20000)
        self.assertEqual(self.cafe.wallet.balance, 0)
        retry = self.client.post('/api/v1/card-transfers/%s/receipt/' % transfer['uuid'], {}, format='multipart')
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(CardTransfer.objects.count(), 1)
        self.assertEqual(TableJoinBaseSerializer(self.join).data['card_transfer']['status'], 'submitted')

    def test_confirm_records_external_payment_once_and_never_charges_customer_wallet(self):
        transfer = self.start()
        self.assertEqual(self.upload(transfer).status_code, 200)
        self.authenticate(self.staff)
        for _ in range(2):
            response = self.review(transfer)
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.pbr.remaining_amount, 0)
        self.assertEqual(self.cafe.wallet.balance, 20000)
        self.assertEqual(self.customer.wallet.balance, 0)
        self.assertEqual(PBRPaymentSession.objects.count(), 1)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(Invoice.objects.get().method, InvoiceConsts.CARD_TO_CARD)

    def test_receipts_and_review_are_scoped_to_customer_and_verified_cafe_staff(self):
        transfer = self.start()
        self.upload(transfer)
        detail = '/api/v1/card-transfers/%s/' % transfer['uuid']
        for profile in (self.outsider, self.other_staff):
            self.authenticate(profile)
            self.assertEqual(self.client.get(detail).status_code, 404)
            self.assertEqual(self.client.get(detail + 'receipt/').status_code, 404)
            self.assertEqual(self.review(transfer).status_code, 404)
        self.authenticate(self.customer)
        self.assertEqual(self.review(transfer).status_code, 403)
        for profile in (self.customer, self.staff):
            self.authenticate(profile)
            response = self.client.get(detail + 'receipt/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(response['Content-Type'], 'image/png')
            # Consume the test client's wrapper so it closes the file without
            # closing the transaction-scoped test database connection.
            self.assertTrue(b''.join(response.streaming_content).startswith(b'\x89PNG'))
        self.authenticate(None)
        self.assertIn(self.client.get(detail + 'receipt/').status_code, (401, 403))
        with self.assertRaises(ValueError):
            CardTransfer.objects.get().receipt.url

    def test_rejection_requires_reason_allows_corrected_receipt_without_canceling_food(self):
        transfer = self.start()
        self.upload(transfer)
        self.authenticate(self.staff)
        self.assertEqual(self.review(transfer, 'reject').status_code, 400)
        self.assertEqual(self.review(transfer, 'reject', 'Wrong receipt').status_code, 200)
        self.assertFalse(Invoice.objects.exists())
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.status, ProductBillRelation.ACCEPTED)
        self.authenticate(self.customer)
        replacement = self.start()
        self.assertNotEqual(replacement['uuid'], transfer['uuid'])
        self.assertEqual(self.upload(replacement, 'green').status_code, 200)

    def test_closed_order_can_receive_a_replacement_receipt_without_reopening_food(self):
        transfer = self.start()
        self.upload(transfer)
        self.join.force_close = True
        self.join.save()
        self.authenticate(self.staff)
        self.assertEqual(self.review(transfer, 'reject', 'Please submit again').status_code, 200)
        self.authenticate(self.customer)
        replacement = self.start()
        self.assertEqual(self.upload(replacement).status_code, 200)
        self.join.refresh_from_db()
        self.assertTrue(self.join.force_close)
        self.authenticate(self.staff)
        self.assertEqual(self.review(replacement).status_code, 200)
        self.assertEqual(self.cafe.wallet.balance, 20000)

    def test_replacement_honors_original_destination_after_store_changes_settings(self):
        transfer = self.start()
        self.upload(transfer)
        self.authenticate(self.staff)
        self.assertEqual(self.review(transfer, 'reject', 'Upload a clearer receipt').status_code, 200)
        self.cafe.card_transfer_enabled = False
        self.cafe.card_transfer_number = '1111222233334444'
        self.cafe.save()
        self.authenticate(self.customer)
        replacement = self.start()
        self.assertEqual(replacement['destination_card'], transfer['destination_card'])
        self.assertEqual(replacement['amount'], transfer['amount'])
        self.assertEqual(self.upload(replacement, 'green').status_code, 200)

    def test_same_image_cannot_submit_two_orders(self):
        transfer = self.start()
        self.upload(transfer)
        other = self.start(self.new_order())
        response = self.upload(other)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(CardTransfer.objects.filter(status='submitted').count(), 1)

    def test_changed_basket_requires_fresh_quote_before_upload(self):
        transfer = self.start()
        self.table.add_product(self.product, self.customer)
        self.assertEqual(self.upload(transfer).status_code, 409)
        self.assertFalse(CardTransfer.objects.get().receipt)
        replacement = self.start()
        self.assertEqual(replacement['amount'], 30000)
        self.assertNotEqual(replacement['uuid'], transfer['uuid'])
        self.assertEqual(CardTransfer.objects.get(uuid=transfer['uuid']).status, 'expired')

    def test_submitted_order_rejects_duplicate_checkout_and_basket_address_fee_edits(self):
        transfer = self.start()
        self.upload(transfer)
        with self.assertRaises(APIBadRequest):
            self.table.add_product(self.product, self.customer)
        with self.assertRaises(APIBadRequest):
            self.table.remove_product(self.product, self.customer)
        for path, data in [('user-profile-address', {'user_profile_address': None}),
                           ('include-delivery-fee', {'include_delivery_fee': True})]:
            response = self.client.patch('/api/v1/join/%s/set/%s/' % (self.join.pk, path), data, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.authenticate(self.staff)
        response = self.client.post('/api/v1/pbr/session/%s/create/' % self.cafe.pk,
            {'payments': [{'pbr': self.pbr.pk, 'amount': 20000}], 'method': InvoiceConsts.CASH}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Invoice.objects.exists())

    def test_disabled_feature_and_other_customer_cannot_start(self):
        self.authenticate(self.outsider)
        url = '/api/v1/join/%s/card-transfer/' % self.join.pk
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 403)
        self.authenticate(self.customer)
        self.cafe.card_transfer_enabled = False
        self.cafe.save()
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)
        self.assertFalse(CardTransfer.objects.exists())

    def test_settings_require_manager_permission_and_normalize_persian_digits(self):
        url = '/api/v1/cafe/%s/card-transfer/settings/' % self.cafe.pk
        self.assertEqual(self.client.get(url).status_code, 403)
        self.authenticate(self.staff)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {'card_transfer_enabled': False}, format='json').status_code, 403)
        self.grant_permission(Cafe, 'can_manage_cafe')
        response = self.client.patch(url, {'card_transfer_number': '۶۰۳۷ ۹۹۱۲ ۳۴۵۶ ۷۸۹۰'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['card_transfer_number'], '6037991234567890')
        for data in ({'card_transfer_number': '123'}, {'card_transfer_holder': ''}):
            self.assertEqual(self.client.patch(url, data, format='json').status_code, 400)

    def test_delivery_fee_is_quoted_and_recorded_exactly_once(self):
        city = City.objects.create(name='Test')
        region = Region.objects.create(name='Local', city=city)
        CafeRegionPrice.objects.create(cafe=self.cafe, region=region, price=5000)
        self.join.address = UserProfileAddress.objects.create(region=region, user_profile=self.customer, address='Test')
        self.join.include_delivery_fee = True
        self.join.save()
        transfer = self.start()
        self.assertEqual(transfer['amount'], 25000)
        self.assertEqual(transfer['delivery_fee'], 5000)
        CafeRegionPrice.objects.filter(cafe=self.cafe, region=region).update(price=8000)
        self.assertEqual(self.upload(transfer).status_code, 200)
        CafeRegionPrice.objects.filter(cafe=self.cafe, region=region).update(price=9000)
        self.authenticate(self.staff)
        self.assertEqual(self.review(transfer).status_code, 200)
        self.assertEqual(self.review(transfer).status_code, 200)
        self.assertEqual(self.cafe.wallet.balance, 25000)
        self.assertEqual(self.join.invoices.get(tag=InvoiceConsts.DELIVERY_FEE).amount, 5000)

    def test_malformed_non_image_and_oversize_files_leave_order_unsubmitted(self):
        transfer = self.start()
        url = '/api/v1/card-transfers/%s/receipt/' % transfer['uuid']
        for contents in (b'not an image', b'<svg><script>alert(1)</script></svg>', b'x' * (8 * 1024 * 1024 + 1)):
            upload = SimpleUploadedFile('receipt.png', contents, content_type='image/png')
            self.assertEqual(self.client.post(url, {'receipt': upload}, format='multipart').status_code, 400)
        self.assertEqual(CardTransfer.objects.get().status, 'draft')
        self.pbr.refresh_from_db()
        self.assertEqual(self.pbr.status, ProductBillRelation.PENDING)

    def test_staff_can_reconcile_after_order_is_delivered(self):
        transfer = self.start()
        self.upload(transfer)
        self.join.force_close = True  # Existing staff Close order action uses this flag.
        self.join.save()
        self.authenticate(self.staff)
        response = self.review(transfer)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.cafe.wallet.balance, 20000)

    def test_receipt_list_is_paginated_and_cafe_scoped(self):
        transfer = self.start()
        self.upload(transfer)
        self.authenticate(self.staff)
        response = self.client.get('/api/v1/cafe/%s/card-transfers/?status=submitted' % self.cafe.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(str(response.data['results'][0]['uuid']), str(transfer['uuid']))
        self.assertEqual(self.client.get('/api/v1/cafe/%s/card-transfers/' % self.other_cafe.pk).status_code, 403)

    def test_new_product_sale_from_creation_through_preparation_and_reconciliation(self):
        self.authenticate(self.staff)
        self.grant_permission(Product, 'can_create_product')
        response = self.client.post('/api/v1/cafe/%s/product/add/' % self.cafe.pk, {
            'name': 'Receipt E2E Coffee', 'original_price': 45000, 'count': 5,
            'category': self.product.category_id, 'discount': 0, 'available': True,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        product = Product.objects.get(pk=response.data['pk'])
        self.pbr.delete()  # Fresh cart containing only the newly created product.
        self.authenticate(self.customer)
        self.table.add_product(product, self.customer, quantity=2)
        transfer = self.start()
        self.assertEqual(transfer['amount'], 90000)
        self.assertEqual(self.upload(transfer).status_code, 200)
        pbr = self.join.all_products.get()
        self.authenticate(self.staff)
        response = self.client.patch('/api/v1/pbr/%s/send-to-kitchen/' % pbr.pk, {'sent_to_kitchen': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        pbr.refresh_from_db()
        self.assertEqual(pbr.status, ProductBillRelation.KITCHEN)
        self.assertFalse(Invoice.objects.exists())  # Kitchen does not wait for a financial approval.
        self.assertEqual(self.review(transfer).status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.count, 3)
        self.assertEqual(pbr.remaining_amount, 0)
        self.assertEqual(self.cafe.wallet.balance, 90000)


class ConcurrentCardTransferTests(ReceiptFixtures, TransactionTestCase):
    def run_parallel(self, operation):
        ready = Barrier(2)
        def run(index):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                ready.wait(timeout=10)
                return operation(index)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as workers:
            return list(workers.map(run, range(2)))

    def test_concurrent_checkout_and_upload_create_one_submission(self):
        ids = self.run_parallel(lambda _: start_transfer(self.join.pk, self.customer).pk)
        self.assertEqual(ids[0], ids[1])
        transfer = CardTransfer.objects.get(pk=ids[0])
        statuses = self.run_parallel(lambda _: submit_receipt(transfer, self.customer, receipt_file()).status)
        self.assertEqual(statuses, ['submitted', 'submitted'])
        self.assertEqual(CardTransfer.objects.count(), 1)
        self.assertFalse(Invoice.objects.exists())

    def test_concurrent_confirmation_credits_the_cafe_once(self):
        transfer = start_transfer(self.join.pk, self.customer)
        transfer = submit_receipt(transfer, self.customer, receipt_file())
        statuses = self.run_parallel(lambda _: review_transfer(transfer, self.staff, 'confirm').status)
        self.assertEqual(statuses, ['confirmed', 'confirmed'])
        self.assertEqual(self.cafe.wallet.balance, 20000)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(PBRPaymentSession.objects.count(), 1)
