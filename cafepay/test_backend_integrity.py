"""Reconciliation output identifies rows without exposing credentials or changing balances."""
import json
from io import StringIO

from django.core.management import call_command
from django.test import TransactionTestCase

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.models import Invoice, PBRPayment, PBRPaymentSession
from cafepay.test_backend_support import BackendFixtures


class IntegrityReportTests(BackendFixtures, TransactionTestCase):
    def test_report_identifies_overpayment_and_duplicate_entries_without_mutation(self):
        invoice = self.cafe.wallet.deposit(amount=25000, status=InvoiceConsts.PAYED,
                                           tag=InvoiceConsts.PAYED_FOR_PRODUCT, item=self.pbr)
        session = PBRPaymentSession.objects.create(user_profile=self.customer, is_manual=True)
        for _ in range(2):
            PBRPayment.objects.create(session=session, pbr=self.pbr, amount=12500)
        original_balance = self.cafe.wallet.balance
        output = StringIO()
        call_command('audit_integrity', stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(report['summary']['overpaid_orders'], 1)
        row = report['findings']['overpaid_orders'][0]
        self.assertEqual(row['id'], self.pbr.pk)
        self.assertEqual(row['excess_amount'], 5000)
        self.assertEqual(row['invoices'][0]['id'], invoice.pk)
        self.assertEqual(report['summary']['duplicate_payment_entries'], 1)
        self.assertNotIn(self.customer.phone_number, output.getvalue())
        self.assertNotIn(self.table_token.token, output.getvalue())
        self.assertEqual(self.cafe.wallet.balance, original_balance)
        self.assertEqual(Invoice.objects.count(), 1)

