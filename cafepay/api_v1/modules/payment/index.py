from cafepay.api_v1.modules.payment.payment_gates import VANDAR, PEP, ZIBAL
from cafepay.api_v1.modules.payment.pep import pep_prepare_for_payment, pep_verify_payment, pep_refund_payment
from cafepay.api_v1.modules.payment.vandar import vandar_prepare_for_payment, vandar_verify_payment

# payment gates
from cafepay.api_v1.modules.payment.zibal import zibal_verify_payment, zibal_prepare_for_payment

# payment gate prepare_for_payment and verify_payment functions
pg_functions = {
    VANDAR: {
        'prepare_for_payment': vandar_prepare_for_payment,
        'verify_payment': vandar_verify_payment,
        'refund_payment': None
    },
    ZIBAL: {
        'prepare_for_payment': zibal_prepare_for_payment,
        'verify_payment': zibal_verify_payment,
        'refund_payment': None
    },
    PEP: {
        'prepare_for_payment': pep_prepare_for_payment,
        'verify_payment': pep_verify_payment,
        'refund_payment': pep_refund_payment
    }
}