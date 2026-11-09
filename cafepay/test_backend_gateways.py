"""Gateway payload tests use mocked transport and never contact payment services."""
import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from cafepay.api_v1.modules.payment.common import get_payable_amount, secure_callback
from cafepay.api_v1.modules.payment.payment_gates import ZIBAL
from cafepay.api_v1.modules.payment.pep import pep_prepare_for_payment, pep_verify_payment
from cafepay.api_v1.modules.payment.vandar import vandar_prepare_for_payment
from cafepay.api_v1.modules.payment.zibal import zibal_prepare_for_payment
from cafepay.test_backend_support import BackendFixtures


def response(body):
    return SimpleNamespace(text=json.dumps(body))


class GatewayPayloadTests(BackendFixtures, TestCase):
    def invoice(self, amount=20000, delivery_fee=5000):
        return self.customer.wallet.deposit(amount=amount, delivery_fee=delivery_fee,
            cafepay_fee=0, auto_clear=True, sub_payment_target_sheba='TEST-ONLY')

    def test_pep_preparation_verification_and_split_payment_use_the_same_units(self):
        invoice = self.invoice()
        request = APIRequestFactory().get('/prepare/', secure=True)
        with patch('requests.post', side_effect=[response({'IsSuccess': True, 'Sign': 'test'}),
                                               response({'IsSuccess': True, 'Token': 'test'})]) as post:
            self.assertEqual(pep_prepare_for_payment(invoice, request)['status'], 200)
        prepare = json.loads(post.call_args_list[0][1]['data'])
        self.assertEqual(prepare['amount'], 250000)
        self.assertTrue(prepare['redirectAddress'].startswith('https://'))
        self.assertNotIn('httpss:', prepare['redirectAddress'])
        self.assertIn('<Amount>250000</Amount>', base64.b64decode(prepare['SubPaymentList']).decode())
        with patch('requests.post', side_effect=[response({'IsSuccess': True, 'Sign': 'test'}),
                                               response({'IsSuccess': True})]) as post:
            self.assertEqual(pep_verify_payment(invoice)[0], True)
        verify = json.loads(post.call_args_list[0][1]['data'])
        self.assertEqual(verify['amount'], prepare['amount'])
        self.assertEqual(post.call_args_list[0][1]['timeout'], (5, 15))

    def test_vandar_accepts_delivery_only_topup_and_includes_delivery(self):
        invoice = self.invoice(amount=0)
        request = APIRequestFactory().get('/prepare/', secure=True)
        with patch('requests.post', return_value=response({'status': 1, 'token': 'test'})) as post:
            self.assertEqual(vandar_prepare_for_payment(invoice, request)['status'], 200)
        data = post.call_args[1]['data']
        self.assertEqual(data['amount'], 50000)
        self.assertTrue(data['callback_url'].startswith('https://'))

    def test_zibal_uses_secure_callback_and_shared_amount(self):
        invoice = self.invoice()
        invoice.payment_gate = ZIBAL
        invoice.save()
        request = APIRequestFactory().get('/prepare/')
        with patch('requests.post', return_value=response({'result': 100, 'trackId': 'test', 'payLink': 'test'})) as post:
            self.assertEqual(zibal_prepare_for_payment(invoice, request)['status'], 200)
        data = post.call_args[1]['json']
        self.assertEqual(data['amount'], 250000)
        self.assertTrue(data['callbackUrl'].startswith('https://'))

    def test_fee_conversion_is_exact_and_preserves_callback_paths(self):
        invoice = self.invoice()
        invoice.cafepay_fee = 0.01
        invoice.fee_payer = False
        self.assertEqual(get_payable_amount(invoice), 252000)
        invoice.fee_payer = True
        self.assertEqual(get_payable_amount(invoice), 250000)
        self.assertEqual(secure_callback('https://example.com/path/http?x=http'),
                         'https://example.com/path/http?x=http')
