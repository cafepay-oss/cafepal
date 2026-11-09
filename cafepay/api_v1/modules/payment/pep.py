import datetime
import json
from decimal import Decimal, ROUND_FLOOR

from django.urls import reverse
from django.utils import timezone

from cafepal.secret import PEP_TERMINAL_CODE, PEP_MERCHANT_CODE, PEP_PRIVATE_KEY
from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import kavenegar_send_sms, datetime_to_asia_tehran
from cafepay.api_v1.modules.payment.common import (
    validate_invoice, get_payable_amount, secure_callback, gateway_post)
import base64


def pep_prepare_for_payment(invoice, request):
    """
    :param invoice: invoice to be prepared for payment
    :param request: django http request object
    :return: on success: {'redirect_to': 'redirect_address', status: 200}
             on error : {'status': status_code, 'details': 'Error descriptions' }
    """

    from cafepay.api_v1.modules.payment.payment_gates import PEP

    # validate invoice
    if not validate_invoice(invoice):
        return {'status': 400, 'details': ["Invalid Invoice", ]}

    callback = request.build_absolute_uri(
        reverse("payment_verify",
                kwargs={
                    'invoice_uuid': invoice.uuid,
                    'pg': PEP})
    )

    callback = secure_callback(callback)

    # set payment timestamp
    invoice.last_payment_timestamp = timezone.now()
    invoice.save()
    cafe_amount = Decimal(invoice.amount) * 10
    if invoice.fee_payer:
        cafe_amount *= 1 - Decimal(str(invoice.cafepay_fee))
    cafe_amount = int(cafe_amount.to_integral_value(rounding=ROUND_FLOOR))
    cafe_amount += invoice.delivery_fee * 10
    amount = get_payable_amount(invoice)

    clear_date = datetime_to_asia_tehran(timezone.now()).date() + datetime.timedelta(days=1)

    subpayment_data = """
        <?xml version="1.0" encoding="utf-8"?>
        <SubPaymentList>
             <SubPayments>
                 <SubPayment>
                     <SubPayID>1</SubPayID>
                     <Amount>%d</Amount>
                     <Date>%s</Date>
                     <Account>%s</Account>
                     <Description></Description>
                 </SubPayment>
             </SubPayments>
        </SubPaymentList>    
        """ % (cafe_amount, str(clear_date),
               invoice.sub_payment_target_sheba)

    subpayment_data = subpayment_data.strip()
    encoded_subpayment = base64.b64encode(subpayment_data.encode('utf-8'))

    sending_data = {
        'invoiceNumber': invoice.pk,
        'invoiceDate': invoice.create_datetime.strftime("%Y/%m/%d %H:%M:%S"),
        'amount': amount,
        'terminalCode': PEP_TERMINAL_CODE,
        'merchantCode': PEP_MERCHANT_CODE,
        'redirectAddress': callback,
        'timeStamp': invoice.last_payment_timestamp.strftime("%Y/%m/%d %H:%M:%S"),
        'action': 1003,
    }

    if hasattr(invoice.wallet, 'user_profile'):
        sending_data['Mobile'] = invoice.wallet.user_profile.phone_number

    if invoice.auto_clear and invoice.sub_payment_target_sheba:
        sending_data['SubPaymentList'] = encoded_subpayment.decode('utf-8')

    sending_data_json = json.dumps(sending_data)

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'Pk': PEP_PRIVATE_KEY.strip()
    }

    signed_data = gateway_post('https://pep.shaparak.ir/Api/v1/Payment/GetSign',
                                headers=headers,
                                data=sending_data_json)
    signed_data_dict = json.loads(signed_data.text)

    if not signed_data_dict.get('IsSuccess'):
        return {'details': signed_data_dict.get('Message', "خطا در پردازش تراکنش"), 'status': 503}

    sign = signed_data_dict.get('Sign')

    headers = {
        'Content-Type': 'Application/json',
        'Sign': sign
    }

    payment_token_data = gateway_post("https://pep.shaparak.ir/Api/v1/Payment/GetToken",
                                       headers=headers, data=sending_data_json)

    payment_token_data_dict = json.loads(payment_token_data.text)

    if not payment_token_data_dict.get('IsSuccess'):
        return {'details': payment_token_data_dict.get('Message', "خطا در پردازش تراکنش"), 'status': 503}

    return {'redirect_to': "https://pep.shaparak.ir/payment.aspx?n=%s" % payment_token_data_dict.get('Token'),
            'status': 200}


def pep_refund_payment(invoice):
    refund_endpoint = "https://pep.shaparak.ir/Api/v1/Payment/RefundPayment"

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'Pk': PEP_PRIVATE_KEY
    }

    invoice.refund_attempt_timestamp = datetime.datetime.now()
    invoice.save()

    sending_data = {
        'invoiceNumber': invoice.pk,
        'invoiceDate': invoice.create_datetime.strftime("%Y/%m/%d %H:%M:%S"),
        'terminalCode': PEP_TERMINAL_CODE,
        'merchantCode': PEP_MERCHANT_CODE,
        'timeStamp': invoice.refund_attempt_timestamp.strftime("%Y/%m/%d %H:%M:%S"),
    }

    sending_data_json = json.dumps(sending_data)

    signed_data = gateway_post('https://pep.shaparak.ir/Api/v1/Payment/GetSign',
                                headers=headers,
                                data=sending_data_json)

    signed_data_dict = json.loads(signed_data.text)

    if not signed_data_dict.get('IsSuccess'):
        kavenegar_send_sms("refundException",
                           {'token': signed_data_dict.get('Message', "خطا در پردازش تراکنش").replace(" ", "")},
                           "09017938091")

        kavenegar_send_sms("refundException",
                           {'token': signed_data_dict.get('Message', "خطا در پردازش تراکنش").replace(" ", "")},
                           "09171164364")
        return False

    sign = signed_data_dict.get('Sign')

    headers = {
        'Content-Type': 'Application/json',
        'Sign': sign
    }

    refund_request = gateway_post(refund_endpoint,
                                   headers=headers, data=sending_data_json)

    refund_dict = json.loads(refund_request.text)

    if not refund_dict.get('IsSuccess'):
        kavenegar_send_sms("refundException",
                           {'token': signed_data_dict.get('Message', "خطا در پردازش تراکنش").replace(" ", "")},
                           "09017938091")

        kavenegar_send_sms("refundException",
                           {'token': signed_data_dict.get('Message', "خطا در پردازش تراکنش").replace(" ", "")},
                           "09171164364")

        return False

    return True


def pep_verify_payment(invoice):
    """Check payment verification"""

    invoice_verification_data_headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'Pk': PEP_PRIVATE_KEY
    }

    amount = get_payable_amount(invoice)

    invoice_verification_data = {
        "InvoiceNumber": invoice.pk,
        'invoiceDate': invoice.create_datetime.strftime("%Y/%m/%d %H:%M:%S"),
        "TerminalCode": PEP_TERMINAL_CODE,
        "MerchantCode": PEP_MERCHANT_CODE,
        'amount': amount,
        'Timestamp': datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }

    verification_data_json = json.dumps(invoice_verification_data)

    signed_data = gateway_post('https://pep.shaparak.ir/Api/v1/Payment/GetSign',
                                headers=invoice_verification_data_headers,
                                data=verification_data_json)
    signed_data_dict = json.loads(signed_data.text)

    if not signed_data_dict.get('IsSuccess'):
        return False, "Could Not Sign Data"

    verification_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Sign': signed_data_dict.get('Sign')
    }

    verification_data = gateway_post('https://pep.shaparak.ir/Api/v1/Payment/VerifyPayment',
                                      headers=verification_headers,
                                      data=verification_data_json)

    verification_data_dict = json.loads(verification_data.text)

    message = verification_data_dict.get('Message', "")
    if verification_data_dict.get('IsSuccess'):
        invoice.status = InvoiceConsts.PAYED
        invoice.save()

    return verification_data_dict.get('IsSuccess'), message


"""
<?xml version="1.0" encoding="utf-8"?>
    <SubPaymentList>
        <SubPayments>
            <SubPayment>
                <SubPayID>1</SubPayID>
                <Amount>40000</Amount>
                <Date>2021/01/27</Date>
                <Account>IR840120010000005779297807</Account>
                <Description></Description>
            </SubPayment>
        </SubPayments>
    </SubPaymentList>
"""
