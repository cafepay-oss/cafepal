import json

from django.urls import reverse

from cafepal.secret import VANDAR_API_KEY, DEMO
from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.modules.payment.common import (
    validate_invoice, get_payable_amount, secure_callback, gateway_post)


def vandar_prepare_for_payment(invoice, request):
    """
    :param invoice: invoice to be prepared for payment
    :param request: django http request object
    :return: on success: {'redirect_to': 'redirect_address', status: 200}
             on error : {'status': status_code, 'details': 'Error descriptions' }
    """

    from cafepay.api_v1.modules.payment.payment_gates import VANDAR

    # validate invoice
    if not validate_invoice(invoice):
        return {'status': 400, 'details': ["Invalid Invoice", ]}

    # generate callback url

    callback = request.build_absolute_uri(
        reverse("payment_verify",
                kwargs={
                    'invoice_uuid': invoice.uuid,
                    'pg': VANDAR})
    )

    callback = secure_callback(callback)

    if DEMO:
        callback = callback.replace('127.0.0.1:8000', 'cafepay.app')

    result = gateway_post(
        'https://ipg.vandar.io/api/v3/send',
        data={
            'api_key': VANDAR_API_KEY,
            'amount': get_payable_amount(invoice),
            'callback_url': callback
        }
    )

    result_data = json.loads(result.text)

    if result_data['status'] != 1:
        return {'details': result_data['errors'], 'status': 503}

    # todo: change invoice status to in payment
    invoice.token = result_data['token']
    invoice.save()

    return {'redirect_to': 'https://ipg.vandar.io/v3/%s' % result_data['token'], 'status': 200}


def vandar_verify_payment(invoice):
    """Check payment verification"""

    result = gateway_post(
        url="https://ipg.vandar.io/api/v3/verify",
        data={
            "api_key": VANDAR_API_KEY,
            "token": invoice.token
        }
    )
    result = json.loads(result.text)

    if result['status'] == 1:
        invoice.status = InvoiceConsts.PAYED
        invoice.transId = result['transId']
        invoice.card_number = result['cardNumber']
    else:
        invoice.status = InvoiceConsts.REJECTED

    invoice.save()

    if invoice.status == InvoiceConsts.PAYED:
        return True
    return False
