from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from base64 import b64encode

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding


def sign(data, key):

    private_key = serialization.load_pem_private_key(
        key,
        password=None,
        backend=default_backend()
    )

    signature = private_key.sign(data, padding.PKCS1v15(), hashes.SHA1())
    signature_base64 = b64encode(signature)
    return signature_base64

