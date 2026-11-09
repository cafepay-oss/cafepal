"""Opposite payment and transfer requests must share deterministic lock ordering."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.modules.payment.payment_gates import LOCAL
from cafepay.api_v1.views.PaymentViews import pay_for_session
from cafepay.models import CafeWallet, Invoice, PBRPayment, PBRPaymentSession, ProductBillRelation, Wallet
from cafepay.test_backend_support import BackendFixtures


class PaymentLockOrderingTests(BackendFixtures, TransactionTestCase):
    def run_parallel(self, operation):
        start = Barrier(2)
        def run(index):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '3s'")
                start.wait(timeout=10)
                return operation(index)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as workers:
            return list(workers.map(run, range(2)))

    def test_opposite_gateway_batches_settle_once_without_deadlock(self):
        other = ProductBillRelation.objects.create(bill=self.bill, product=self.product,
            user_profile=self.customer, count=2, original_price=10000, discount=0)
        sessions = []
        for order in ((self.pbr, other), (other, self.pbr)):
            invoice = Invoice.objects.create(wallet=self.customer.wallet, amount=40000,
                status=InvoiceConsts.PAYED, type=InvoiceConsts.DEPOSIT,
                payment_gate=LOCAL, token='mock_test')
            session = PBRPaymentSession.objects.create(user_profile=self.customer, invoice=invoice)
            for pbr in order:
                PBRPayment.objects.create(session=session, pbr=pbr, amount=20000)
            sessions.append(session)
        results = self.run_parallel(lambda index: pay_for_session(sessions[index], sessions[index].invoice)[1])
        self.assertCountEqual(results, [200, 400])
        self.assertEqual(self.pbr.remaining_amount, 0)
        self.assertEqual(other.remaining_amount, 0)
        self.assertEqual(self.cafe.wallet.balance, 40000)
        self.assertEqual(self.customer.wallet.balance, 40000)

    def test_opposite_wallet_transfers_finish_without_lost_funds(self):
        wallets = [self.customer.wallet, self.outsider.wallet]
        for wallet in wallets:
            wallet.deposit(amount=1000, status=InvoiceConsts.INTERNAL)
        ready = Barrier(2)
        def transfer(index):
            for _ in range(20):
                ready.wait(timeout=10)
                result = wallets[index].transfer(1, wallets[1 - index], status=InvoiceConsts.INTERNAL)
                self.assertIsNotNone(result)
            return True
        self.assertEqual(self.run_parallel(transfer), [True, True])
        self.assertEqual([wallet.balance for wallet in wallets], [1000, 1000])

    def test_concurrent_cafe_wallet_creation_has_no_orphan_wallet(self):
        before = Wallet.objects.count()
        results = self.run_parallel(lambda _: CafeWallet.get_or_create(self.customer, self.cafe).pk)
        self.assertEqual(results[0], results[1])
        self.assertEqual(CafeWallet.objects.filter(user_profile=self.customer, cafe=self.cafe).count(), 1)
        self.assertEqual(Wallet.objects.count(), before + 1)
