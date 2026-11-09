"""Receipt-first checkout. Receipt submission never claims bank verification."""
import hashlib
import io
import json
import logging
import threading
from uuid import uuid4

from PIL import Image
from django.core.files.base import ContentFile
from django.db import transaction, IntegrityError
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import notify_watchers, _desktop_notification_thread
from cafepay.models import (CardTransfer, Invoice, PBRPayment, PBRPaymentSession,
                           ProductBillRelation, Table, TableJoin, Wallet)

logger = logging.getLogger(__name__)
MAX_RECEIPT_BYTES = 8 * 1024 * 1024


class TransferConflict(APIException):
    status_code = 409
    default_detail = 'اطلاعات سفارش تغییر کرده است؛ لطفا مبلغ را دوباره بررسی کنید.'


def locked_order(join_id):
    join = get_object_or_404(TableJoin, pk=join_id)
    # Share the table locks used by basket edits, then lock receipts/items.
    list(Table.objects.select_for_update().filter(
        pk__in=join.bills.values('table_id')).order_by('pk'))
    join.refresh_from_db()
    return join


def order_quote(join, customer, allow_closed=False, transfer=None):
    if (join.force_close or join.sent) and not allow_closed:
        raise TransferConflict('این سفارش بسته شده است.')
    products = list(join.all_products.select_for_update().filter(count__gt=0)
                    .exclude(status=ProductBillRelation.CANCELED).order_by('pk'))
    if not products:
        raise ValidationError('سفارش خالی است.')
    if any(pbr.user_profile_id != customer.private_id or pbr.product.cafe_id != join.cafe_id
           for pbr in products):
        raise PermissionDenied('فقط صاحب سفارش می‌تواند رسید پرداخت را ارسال کند.')
    items = [{'pbr': pbr.pk, 'amount': pbr.remaining_amount} for pbr in products
             if pbr.remaining_amount > 0]
    fee = 0
    paid_fee = 0
    if join.include_delivery_fee:
        if not join.address:
            raise ValidationError('لطفا آدرس معتبر برای ارسال انتخاب کنید.')
        paid_fee = join.invoices.filter(tag=InvoiceConsts.DELIVERY_FEE, type=InvoiceConsts.DEPOSIT,
            status__in=[InvoiceConsts.PAYED, InvoiceConsts.INTERNAL]).aggregate(total=Sum('amount'))['total'] or 0
        if transfer:
            # Honor the amount shown before the customer left for their banking app.
            fee = transfer.delivery_fee
        else:
            region = join.cafe.delivery_regions.filter(region_id=join.address.region_id).first()
            if not region:
                raise ValidationError('لطفا آدرس معتبر برای ارسال انتخاب کنید.')
            fee = max(0, region.price - paid_fee)
    amount = sum(item['amount'] for item in items) + fee
    if not items or amount <= 0:
        raise TransferConflict('این سفارش قبلا پرداخت شده است.')
    fingerprint = hashlib.sha256(json.dumps({
        'items': items, 'products': [(p.pk, p.count, p.original_price, p.discount) for p in products],
        'address': join.address_id, 'delivery_fee': fee, 'paid_delivery_fee': paid_fee,
        'include_delivery_fee': join.include_delivery_fee, 'is_self_pickup': join.is_self_pickup,
    }, sort_keys=True).encode()).hexdigest()
    return items, fee, amount, fingerprint


def start_transfer(join_id, customer):
    with transaction.atomic():
        join = locked_order(join_id)
        # Scope ownership before returning even an existing payment reference.
        if not join.all_products.filter(user_profile=customer).exists():
            raise PermissionDenied()
        existing = join.card_transfers.select_for_update().filter(
            status__in=[CardTransfer.DRAFT, CardTransfer.SUBMITTED]).first()
        if existing and existing.customer_id != customer.pk:
            raise PermissionDenied()
        if existing and existing.status == CardTransfer.SUBMITTED:
            return existing
        previous = join.card_transfers.filter(status=CardTransfer.REJECTED, customer=customer).first()
        snapshot = existing or previous
        cafe = join.cafe
        items, fee, amount, fingerprint = order_quote(
            join, customer, allow_closed=bool(previous), transfer=snapshot)
        same_order = snapshot and snapshot.order_fingerprint == fingerprint
        if existing and same_order:
            return existing
        if not same_order:
            if not cafe.card_transfer_enabled or not cafe.card_transfer_number or not cafe.card_transfer_holder:
                raise ValidationError('پرداخت کارت‌به‌کارت در این مجموعه فعال نیست.')
            # A changed basket needs a fresh quote. An unchanged receipt replacement
            # keeps the original destination and fee, even after settings change.
            items, fee, amount, fingerprint = order_quote(join, customer, allow_closed=bool(previous))
        if existing:
            existing.status = CardTransfer.EXPIRED
            existing.save(update_fields=['status'])
        return CardTransfer.objects.create(cafe=cafe, join=join, customer=customer,
            amount=amount, delivery_fee=fee, items=items, order_fingerprint=fingerprint,
            destination_card=snapshot.destination_card if same_order else cafe.card_transfer_number,
            destination_holder=snapshot.destination_holder if same_order else cafe.card_transfer_holder)


def receipt_image(upload):
    if upload is None or upload.size > MAX_RECEIPT_BYTES:
        raise ValidationError('یک تصویر رسید با حجم حداکثر ۸ مگابایت انتخاب کنید.')
    try:
        source = Image.open(upload)
        if source.format not in ('JPEG', 'PNG', 'WEBP') or source.width * source.height > 16000000:
            raise ValueError()
        source.load()
        # Normalize orientation and remove metadata; never serve the supplied file bytes.
        from PIL import ImageOps
        source = ImageOps.exif_transpose(source).convert('RGB')
        source.thumbnail((2000, 2000))
        output = io.BytesIO()
        source.save(output, format='PNG')
        data = output.getvalue()
        if len(data) > MAX_RECEIPT_BYTES:
            raise ValueError()
        return data, hashlib.sha256(data).hexdigest()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError('تصویر رسید خوانا نیست. لطفا یک فایل PNG یا JPG انتخاب کنید.')


def notify_order(join_id, new_order=False):
    try:
        for table in Table.objects.filter(pk__in=TableJoin.objects.get(pk=join_id).bills.values('table_id')):
            notify_watchers(table)
            if new_order and table.is_preorder:
                threading.Thread(target=_desktop_notification_thread, args=(table,), daemon=True).start()
    except Exception:
        logger.exception('Card transfer order notification failed')


def submit_receipt(transfer, customer, upload):
    if transfer.customer_id != customer.pk:
        raise PermissionDenied()
    # A response lost after upload can be retried without another file or duplicate work.
    if transfer.status in (CardTransfer.SUBMITTED, CardTransfer.CONFIRMED):
        return transfer
    data, checksum = receipt_image(upload)
    saved_name = None
    storage = CardTransfer._meta.get_field('receipt').storage
    try:
        with transaction.atomic():
            join = locked_order(transfer.join_id)
            transfer = CardTransfer.objects.select_for_update().get(pk=transfer.pk)
            if transfer.status in (CardTransfer.SUBMITTED, CardTransfer.CONFIRMED):
                return transfer
            if transfer.status != CardTransfer.DRAFT:
                raise TransferConflict('لطفا برای ارسال رسید، پرداخت را دوباره باز کنید.')
            replacement = join.card_transfers.filter(status=CardTransfer.REJECTED, customer=customer).exists()
            _, _, _, fingerprint = order_quote(join, customer, allow_closed=replacement, transfer=transfer)
            if fingerprint != transfer.order_fingerprint:
                raise TransferConflict()
            if CardTransfer.objects.filter(receipt_checksum=checksum).exclude(join_id=join.pk).exists():
                raise TransferConflict('این تصویر قبلا برای سفارش دیگری ثبت شده است. رسید همین پرداخت را انتخاب کنید.')
            transfer.receipt.save('%s.png' % uuid4().hex, ContentFile(data), save=False)
            saved_name = transfer.receipt.name
            transfer.receipt_checksum = checksum
            transfer.status = CardTransfer.SUBMITTED
            transfer.submitted_at = timezone.now()
            transfer.save()
            # Optimistic fulfillment: no approval queue blocks kitchen preparation.
            join.all_products.filter(status=ProductBillRelation.PENDING).update(status=ProductBillRelation.ACCEPTED)
            join.all_products.update(preferred_payment_method=InvoiceConsts.CARD_TO_CARD)
            transaction.on_commit(lambda: notify_order(join.pk, new_order=not replacement))
            return transfer
    except Exception as error:
        if saved_name:
            storage.delete(saved_name)
        if isinstance(error, IntegrityError):
            raise TransferConflict('این رسید قبلا ثبت شده است؛ وضعیت سفارش را تازه‌سازی کنید.')
        raise


def review_transfer(transfer, reviewer, decision, note=''):
    with transaction.atomic():
        join = locked_order(transfer.join_id)
        transfer = CardTransfer.objects.select_for_update().get(pk=transfer.pk)
        target = CardTransfer.CONFIRMED if decision == 'confirm' else CardTransfer.REJECTED
        if transfer.status == target:
            return transfer
        if transfer.status != CardTransfer.SUBMITTED:
            raise TransferConflict('وضعیت این رسید قبلا تغییر کرده است.')
        if decision == 'confirm':
            items, fee, amount, fingerprint = order_quote(join, transfer.customer, allow_closed=True, transfer=transfer)
            if fingerprint != transfer.order_fingerprint or amount != transfer.amount:
                raise TransferConflict('مبلغ سفارش تغییر کرده است. قبل از تایید، گردش حساب را بررسی کنید.')
            # External money was received by the cafe, never by the customer's app wallet.
            Wallet.objects.select_for_update().get(pk=transfer.cafe.wallet_id)
            session = PBRPaymentSession.objects.create(user_profile=reviewer,
                is_manual=True, method=InvoiceConsts.CARD_TO_CARD)
            for item in items:
                pbr = ProductBillRelation.objects.get(pk=item['pbr'])
                PBRPayment.objects.create(session=session, pbr=pbr, amount=item['amount'])
                transfer.cafe.wallet.deposit(amount=item['amount'], status=InvoiceConsts.PAYED,
                    tag=InvoiceConsts.PAYED_FOR_PRODUCT, method=InvoiceConsts.CARD_TO_CARD, item=pbr)
            if fee:
                transfer.cafe.wallet.deposit(amount=fee, status=InvoiceConsts.PAYED,
                    tag=InvoiceConsts.DELIVERY_FEE, method=InvoiceConsts.CARD_TO_CARD, item=join)
            transfer.payment_session = session
        transfer.status = target
        transfer.reviewed_at = timezone.now()
        transfer.reviewed_by = reviewer
        transfer.review_note = note
        transfer.save()
        transaction.on_commit(lambda: notify_order(join.pk))
        return transfer
