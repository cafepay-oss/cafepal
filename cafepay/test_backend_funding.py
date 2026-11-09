"""Wallet funds and gateway credit must cover orders and delivery exactly once."""
from django.test import TestCase, override_settings

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.views.PaymentViews import pay_for_session
from cafepay.models import CafeRegionPrice, City, PBRPaymentSession, Region, UserProfileAddress
from cafepay.test_backend_support import BackendFixtures


@override_settings(CAFEPAY_LOCAL_RECOVERY=True, CAFEPAY_MOCK_PAYMENTS=True)
class WalletFundingTests(BackendFixtures, TestCase):
    def enable_delivery(self, fee=5000):
        region = Region.objects.create(city=City.objects.create(name='Test'), name='Test')
        self.join.include_delivery_fee = True
        self.join.address = UserProfileAddress.objects.create(
            region=region, user_profile=self.customer, address='Test')
        self.join.save()
        CafeRegionPrice.objects.create(cafe=self.cafe, region=region, price=fee)

    def checkout(self, balance):
        self.customer.wallet.deposit(amount=balance, status=InvoiceConsts.PAYED)
        self.authenticate(self.customer)
        response = self.client.post('/api/v1/pbr/session/create/', {
            'payments': [{'pbr': self.pbr.pk, 'amount': 20000}], 'use_wallet': True,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return PBRPaymentSession.objects.get(pk=response.data['pk'])

    def settle(self, session):
        invoice = session.invoice
        invoice.status = InvoiceConsts.PAYED
        invoice.save()
        self.assertEqual(pay_for_session(session, invoice)[1], 200)

    def test_wallet_only_delivery_does_not_create_new_money(self):
        self.enable_delivery()
        session = self.checkout(25000)
        self.assertTrue(session.invoice.fake)
        self.assertEqual(session.invoice.amount, 0)
        self.settle(session)
        self.assertEqual(self.customer.wallet.balance, 0)
        self.assertEqual(self.cafe.wallet.balance, 25000)
        self.assertEqual(self.pbr.remaining_amount, 0)

    def test_real_gateway_settlement_combines_existing_wallet_credit(self):
        session = self.checkout(5000)
        self.assertFalse(session.invoice.fake)
        self.assertEqual(session.invoice.amount, 15000)
        self.settle(session)
        self.assertEqual(self.customer.wallet.balance, 0)
        self.assertEqual(self.cafe.wallet.balance, 20000)

    def test_delivery_shortfall_requires_new_credit(self):
        self.enable_delivery()
        session = self.checkout(20000)
        self.assertFalse(session.invoice.fake)
        self.assertEqual(session.invoice.amount + session.invoice.delivery_fee, 5000)
        self.settle(session)
        self.assertEqual(self.customer.wallet.balance, 0)
        self.assertEqual(self.cafe.wallet.balance, 25000)
