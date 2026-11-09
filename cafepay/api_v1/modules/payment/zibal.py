import json

from django.urls import reverse

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.modules.payment.common import (
    validate_invoice, get_payable_amount, secure_callback, gateway_post)


def zibal_prepare_for_payment(invoice, request):
    """
    :param invoice: invoice to be prepared for payment
    :param request: django http request object
    :return: on success: {'redirect_to': 'redirect_address', status: 200}
             on error : {'status': status_code, 'details': 'Error descriptions' }
    """

    from cafepay.api_v1.modules.payment.payment_gates import ZIBAL

    # validate invoice
    if not validate_invoice(invoice):
        return {'status': 400, 'details': ["Invalid Invoice", ]}

    if invoice.payment_gate != ZIBAL:
        return {'status': 400, 'details': ["Gate Should Be ZIBAL", ]}

    # generate callback url

    callback = request.build_absolute_uri(
        reverse("payment_verify",
                kwargs={
                    'invoice_uuid': invoice.uuid,
                    'pg': ZIBAL})
    )
    callback = secure_callback(callback)

    amount = get_payable_amount(invoice)

    result = gateway_post(
        'https://gateway.zibal.ir/v1/request',
        json={
            'merchant': invoice.merchant,
            'amount': amount,
            'callbackUrl': callback,
            'linkToPay': True
        }
    )

    result_data = json.loads(result.text)

    if result_data['result'] != 100:
        return {'details': result_data, 'status': 503}

    # todo: change invoice status to in payment
    invoice.token = result_data['trackId']
    invoice.save()

    return {'redirect_to': result_data.get('payLink'), 'status': 200}


def zibal_verify_payment(invoice):
    """Check payment verification"""

    result = gateway_post(
        url="https://gateway.zibal.ir/v1/verify",
        json={
            "merchant": invoice.merchant,
            "trackId": invoice.token
        }
    )
    result = json.loads(result.text)
    if result.get('result') == 100 and result.get('status') == 1:
        invoice.status = InvoiceConsts.PAYED
        invoice.card_number = result['cardNumber']
    else:
        invoice.status = InvoiceConsts.REJECTED
    invoice.save()
    if invoice.status == InvoiceConsts.PAYED:
        return True, result.get('message')
    return False, result.get('message')
