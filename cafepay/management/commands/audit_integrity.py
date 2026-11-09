"""Read-only reconciliation evidence. Never changes historical rows."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Coalesce

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.models import Bill, Invoice, PBRPayment, Product, ProductBillRelation, TableToken


def token_groups(token_type):
    groups = list(TableToken.objects.filter(type=token_type).values('cafe_id')
                  .annotate(count=Count('pk')).filter(count__gt=1).order_by('cafe_id'))
    by_cafe = {group['cafe_id']: [] for group in groups}
    rows = TableToken.objects.filter(cafe_id__in=by_cafe, type=token_type).values(
        'id', 'cafe_id', 'table_id', 'status').order_by('id')
    for row in rows:
        by_cafe[row['cafe_id']].append(row)
    for group in groups:
        group['rows'] = by_cafe[group['cafe_id']]
    return groups


def build_report():
    paid = Q(invoices__status__in=[InvoiceConsts.PAYED, InvoiceConsts.INTERNAL],
             invoices__type=InvoiceConsts.DEPOSIT, invoices__tag=InvoiceConsts.PAYED_FOR_PRODUCT)
    refunded = Q(invoices__status__in=[InvoiceConsts.PAYED, InvoiceConsts.INTERNAL],
                 invoices__type=InvoiceConsts.WITHDRAW, invoices__tag=InvoiceConsts.REFUND)
    balances = ProductBillRelation.objects.annotate(
        paid_total=Coalesce(Sum('invoices__amount', filter=paid), Value(0)),
        refund_total=Coalesce(Sum('invoices__amount', filter=refunded), Value(0)),
        order_total=RawSQL('cafepay_productbillrelation.count * FLOOR('
                          'cafepay_productbillrelation.original_price * '
                          '(100 - cafepay_productbillrelation.discount) / 100.0)', []))
    overpaid = list(balances.filter(paid_total__gt=F('refund_total') + F('order_total'))
                   .values('id', 'bill_id', 'product_id', 'paid_total', 'refund_total', 'order_total')
                   .order_by('id'))
    invoices_by_pbr = {row['id']: [] for row in overpaid}
    for invoice in Invoice.objects.filter(pbr__pk__in=invoices_by_pbr).values(
            'id', 'item_id', 'amount', 'type', 'status', 'tag', 'wallet_id').order_by('id'):
        invoices_by_pbr[invoice['item_id']].append(invoice)
    for row in overpaid:
        row['order_total'] = int(row['order_total'])
        row['excess_amount'] = row['paid_total'] - row['refund_total'] - row['order_total']
        row['invoices'] = invoices_by_pbr[row['id']]
    duplicate_payments = list(PBRPayment.objects.values('session_id', 'pbr_id')
                             .annotate(count=Count('pk'), amount=Sum('amount')).filter(count__gt=1)
                             .order_by('session_id', 'pbr_id'))
    payments_by_pair = {(row['session_id'], row['pbr_id']): [] for row in duplicate_payments}
    payment_rows = PBRPayment.objects.filter(
        session_id__in={row['session_id'] for row in duplicate_payments}).values(
            'id', 'session_id', 'pbr_id', 'amount', 'session__is_manual',
            'session__invoice_id', 'session__invoice__status').order_by('id')
    for row in payment_rows:
        key = (row['session_id'], row['pbr_id'])
        if key in payments_by_pair:
            payments_by_pair[key].append(row)
    for row in duplicate_payments:
        row['rows'] = payments_by_pair[(row['session_id'], row['pbr_id'])]
    active = Bill.objects.filter(join__force_close=False, join__sent=False)
    duplicate_bills = list(active.values('table_id').annotate(count=Count('pk'))
                           .filter(count__gt=1).order_by('table_id'))
    bills_by_table = {row['table_id']: [] for row in duplicate_bills}
    for bill in active.filter(table_id__in=bills_by_table).values('pk', 'table_id'):
        bills_by_table[bill['table_id']].append(bill['pk'])
    for row in duplicate_bills:
        row['bill_ids'] = bills_by_table[row['table_id']]
    findings = {
        'duplicate_menu_token_groups': token_groups(TableToken.MENU_ONLY),
        'duplicate_preorder_token_groups': token_groups(TableToken.SELF_PICKUP),
        'duplicate_active_bill_tables': duplicate_bills,
        'negative_product_stock': list(Product.objects.filter(count__lt=0).values('id', 'cafe_id', 'count')),
        'negative_order_quantity': list(ProductBillRelation.objects.filter(count__lt=0).values('id', 'bill_id', 'count')),
        'cross_cafe_product_categories': list(Product.objects.exclude(cafe_id=F('category__cafe_id'))
            .values('id', 'cafe_id', 'category_id', 'category__cafe_id').order_by('id')),
        'cross_cafe_product_groups': list(Product.objects.filter(group__isnull=False).exclude(cafe_id=F('group__cafe_id'))
            .values('id', 'cafe_id', 'group_id', 'group__cafe_id').order_by('id')),
        'cross_cafe_order_products': list(ProductBillRelation.objects.exclude(product__cafe_id=F('bill__table__cafe_id'))
            .values('id', 'product_id', 'product__cafe_id', 'bill_id', 'bill__table__cafe_id').order_by('id')),
        'duplicate_payment_entries': duplicate_payments,
        'mixed_cafe_payment_sessions': list(PBRPayment.objects.values('session_id')
            .annotate(cafe_count=Count('pbr__bill__table__cafe_id', distinct=True)).filter(cafe_count__gt=1)),
        'negative_invoices': list(Invoice.objects.filter(amount__lt=0).values('id', 'amount', 'wallet_id')),
        'overpaid_orders': overpaid,
    }
    return {
        'schema_version': 1,
        'summary': {name: len(rows) for name, rows in findings.items()},
        'findings': findings,
        'reconciliation_policy': {
            'duplicate_tokens': 'Multiple tokens can be intentional. Confirm printed QR use before retiring any token or table.',
            'cross_cafe_categories': 'Confirm the product owner and intended category. Reassign only after that decision.',
            'cross_cafe_orders': 'Confirm the sale cafe and historical wallet destination before changing any relation.',
            'duplicate_payments': 'Compare session status and invoice rows. Repeated entries can be unpaid attempts or intended splits.',
            'overpaid_orders': 'Compare listed invoices with external receipts and refunds. Preserve invoices; use an explicit correcting transaction.',
            'active_bills': 'Choose the active order after reviewing its items and payments. Do not merge automatically.',
            'stock': 'Confirm actual inventory before adjusting counts. Do not infer physical stock from old orders.',
        },
    }


class Command(BaseCommand):
    help = 'Report historical integrity candidates without changing data or exposing personal data or tokens.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('This audit requires PostgreSQL read-only transactions.')
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
            report = build_report()
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
