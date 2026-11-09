"""Shared gateway units, callback normalization, and bounded transport."""
from decimal import Decimal, ROUND_CEILING
from urllib.parse import urlsplit

import requests

from cafepay.api_v1.consts import InvoiceConsts


def validate_invoice(invoice):
    return invoice.fake or (invoice.status not in (
        InvoiceConsts.PAYED, InvoiceConsts.INTERNAL, InvoiceConsts.IN_PAYMENT)
        and invoice.amount + invoice.delivery_fee >= 1000)


def get_payable_amount(invoice):
    # Ledger values use toman; every gateway payload uses integer rials.
    amount = Decimal(invoice.amount) * 10
    if not invoice.fee_payer:
        amount += amount * Decimal(str(invoice.cafepay_fee))
    amount += Decimal(invoice.delivery_fee) * 10
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def secure_callback(url):
    return urlsplit(url)._replace(scheme='https').geturl()


def gateway_post(*args, **kwargs):
    kwargs.setdefault('timeout', (5, 15))
    return requests.post(*args, **kwargs)
