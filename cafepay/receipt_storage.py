"""Receipts are served by authenticated views, never by the public media host."""
import os
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateReceiptStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(file_permissions_mode=0o600, directory_permissions_mode=0o700)

    @property
    def location(self):
        return os.path.abspath(settings.PRIVATE_MEDIA_ROOT)

    def url(self, name):
        raise ValueError('Payment receipts require authenticated access.')
