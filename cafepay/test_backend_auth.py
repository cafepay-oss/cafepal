"""SMS codes expire, throttle resends, and permit only one successful use."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from cafepay.models import UserProfilePhoneVerification
from cafepay.test_backend_support import BackendFixtures


class VerificationFixtures(BackendFixtures):
    def setUp(self):
        super().setUp()
        sms = patch('cafepay.models.send_verification_code')
        self.sms = sms.start()
        self.addCleanup(sms.stop)
        self.verification = UserProfilePhoneVerification.objects.create(
            user_profile=self.customer, code='12345')['obj']


class PhoneVerificationTests(VerificationFixtures, TestCase):
    def test_expired_codes_fail_for_customer_and_staff_login(self):
        UserProfilePhoneVerification.objects.filter(pk=self.verification.pk).update(
            create_date=timezone.now() - timedelta(minutes=6))
        for route, field in (('user_profile_auth_token', 'code'), ('cafe_auth_token', 'password')):
            response = self.client.post(reverse(route), {
                'phone_number': self.customer.phone_number, field: '12345'}, format='json')
            self.assertEqual(response.status_code, 404, response.data)

    def test_resend_is_throttled_and_new_code_invalidates_old_code(self):
        result = UserProfilePhoneVerification.objects.create(user_profile=self.customer)
        self.assertEqual(result['status'], 403)
        self.assertEqual(UserProfilePhoneVerification.objects.count(), 1)
        self.assertEqual(self.sms.call_count, 1)
        UserProfilePhoneVerification.objects.filter(pk=self.verification.pk).update(
            create_date=timezone.now() - timedelta(minutes=2))
        result = UserProfilePhoneVerification.objects.create(user_profile=self.customer, code='67890')
        self.assertEqual(result['status'], 201)
        self.verification.refresh_from_db()
        self.assertTrue(self.verification.burnt)

    def test_attempt_limit_and_single_use(self):
        manager = UserProfilePhoneVerification.objects
        for remaining in range(4, -1, -1):
            self.assertEqual(manager.consume(self.customer.phone_number, 'wrong')['allowed_retry_times'], remaining)
        self.assertEqual(manager.consume(self.customer.phone_number, '12345')['status'], 404)
        self.verification.query_times = 0
        self.verification.save(update_fields=['query_times'])
        self.assertEqual(manager.consume(self.customer.phone_number, '12345')['status'], 200)
        self.assertEqual(manager.consume(self.customer.phone_number, '12345')['status'], 404)


class ConcurrentPhoneVerificationTests(VerificationFixtures, TransactionTestCase):
    def test_code_can_only_be_consumed_once_concurrently(self):
        ready = Barrier(2)
        def consume(_):
            close_old_connections()
            try:
                ready.wait(timeout=10)
                return UserProfilePhoneVerification.objects.consume(self.customer.phone_number, '12345')['status']
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(consume, range(2)))
        self.assertCountEqual(results, [200, 404])
