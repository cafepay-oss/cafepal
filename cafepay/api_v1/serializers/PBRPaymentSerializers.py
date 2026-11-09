from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework import serializers

from cafepal import settings
from cafepay.api_v1.consts import InvoiceConsts
from cafepay.api_v1.helpers import get_user_profile_basic_info_serializer
from cafepay.api_v1.modules.payment.mock import mock_enabled
from cafepay.api_v1.serializers.WalletAndInvoiceSerializers import PaymentInvoicesSerializer, InvoiceSerializer
from cafepay.models import PBRPayment, PBRPaymentSession, Cafe, ProductBillRelation, UserProfile, Invoice, CafeWallet, \
    PaymentSession, PBRRefund, Wallet


def validate_distinct_payments(payments):
    if not payments:
        raise serializers.ValidationError(_('Cannot create empty session'))
    ids = [payment['pbr'].pk for payment in payments]
    if len(ids) != len(set(ids)):
        raise serializers.ValidationError(_('Duplicate payment item'))
    return payments


def lock_payments(payments):
    """Recheck balances under locks before any ledger records are created."""
    validate_distinct_payments(payments)
    locked = {pbr.pk: pbr for pbr in ProductBillRelation.objects.select_for_update()
              .filter(pk__in=[payment['pbr'].pk for payment in payments]).order_by('pk')}
    result = []
    for payment in payments:
        pbr = locked.get(payment['pbr'].pk)
        if not pbr or payment['amount'] <= 0 or payment['amount'] > pbr.remaining_amount:
            raise serializers.ValidationError({'amount': _('Exceeded remaining amount')})
        owner = pbr.bill.current_owner or pbr.bill
        if owner.join_id and owner.join.card_transfers.filter(status='submitted').exists():
            raise serializers.ValidationError('رسید این سفارش ثبت شده است؛ پرداخت را از بخش رسیدها بررسی کنید.')
        result.append(dict(payment, pbr=pbr))
    return result


class PBRPaymentCreateSerializer(serializers.ModelSerializer):
    amount = serializers.IntegerField(min_value=1)

    class Meta:
        model = PBRPayment
        fields = ['pk', 'pbr', 'amount']

    def validate(self, attrs):
        pbr = attrs.get('pbr')
        amount = attrs.get('amount')

        if amount > pbr.remaining_amount:
            raise serializers.ValidationError({'amount': _("Exceeded remaining amount")})

        return attrs


class PBRPaymentSessionCreateSerializer(serializers.ModelSerializer):
    payments = PBRPaymentCreateSerializer(many=True)
    invoice_uuid = serializers.SerializerMethodField()

    use_wallet = serializers.BooleanField(default=True, write_only=True)

    class Meta:
        model = PBRPaymentSession
        fields = ['pk', 'payments', 'user_profile', 'use_wallet', 'invoice_uuid']

        extra_kwargs = {
            'user_profile': {'read_only': True}
        }

    @staticmethod
    def get_invoice_uuid(instance):
        if not instance.invoice:
            return None
        return instance.invoice.uuid

    @staticmethod
    def validate_payments(payments):
        validate_distinct_payments(payments)
        join_id = None
        for payment in payments:
            pbr = payment['pbr']
            bill = pbr.bill.current_owner
            if (not bill or (join_id is not None and bill.join_id != join_id) or
                    pbr.product.cafe_id != bill.table.cafe_id):
                raise serializers.ValidationError(_('Payments must belong to one active order'))
            join_id = bill.join_id
            pbr._current_payment_bill = bill
        bill = payments[0]['pbr']._current_payment_bill
        _table = bill.table
        _cafe = _table.cafe
        _active_join = bill.join

        if not mock_enabled() and (not _cafe.payment_gate or not _cafe.merchant) and not _cafe.use_default_gate:
            raise serializers.ValidationError(_("Invalid Payment Gate or merchant"))

        if _active_join.include_delivery_fee:
            if not _active_join.address:
                raise serializers.ValidationError(_("Include fee is true but no address is set"))

            if _active_join.address.region not in [crp.region for crp in _cafe.delivery_regions.all()]:
                raise serializers.ValidationError(_("No delivery in the selected area"))

        return payments

    def create(self, validated_data):
        with transaction.atomic():
            payments_data = lock_payments(validated_data.pop('payments'))
            self.validate_payments(payments_data)
            use_wallet = validated_data.pop('use_wallet')

            # create the session
            pbrps = PBRPaymentSession.objects.create(**validated_data)
            payment_session = PaymentSession.objects.create()

            # create pbr payments
            for payment_data in payments_data:
                pbr_payment = PBRPayment.objects.create(session=pbrps, **payment_data)

            _table = payments_data[0]['pbr']._current_payment_bill.table
            _cafe = _table.cafe

            # create invoice for payment
            cafe = _table.cafe
            active_join = payments_data[0]['pbr']._current_payment_bill.join
            if active_join.include_delivery_fee:
                delivery_region = cafe.delivery_regions.get(region=active_join.address.region)
                delivery_fee = delivery_region.price
            else:
                delivery_fee = 0
            user_profile = validated_data.get('user_profile')
            wallet = user_profile.wallet
            user_profile_cafe_wallet = CafeWallet.objects.filter(
                cafe=cafe, user_profile=user_profile).select_related('wallet').first()
            wallet_ids = [wallet.pk]
            if user_profile_cafe_wallet:
                wallet_ids.append(user_profile_cafe_wallet.wallet_id)
            list(Wallet.objects.select_for_update().filter(pk__in=wallet_ids).order_by('pk'))
            wallet_balance = wallet.balance
            if user_profile_cafe_wallet:
                wallet_balance += user_profile_cafe_wallet.wallet.balance

            # if use_wallet:
            # case 1: enough balance: create fake deposit invoice (used to proceed into the verification step)
            # case 2: not enough balance, but remaining is less than minimum payable:
            # create a deposit invoice with the min payable amount
            # case 3: not enough balance, and remaining is equal or grater than minimum payable:
            # create a deposit invoice with the remaining amount

            # case not use_wallet:
            is_fake = False
            min_amount = 1000

            # case use wallet
            if use_wallet:
                required_amount = pbrps.total_amount + delivery_fee
                if wallet_balance >= required_amount:
                    deposit_amount = 0
                    is_fake = True
                else:
                    gateway_total = max(min_amount, required_amount - wallet_balance)
                    deposit_amount = max(0, gateway_total - delivery_fee)
            else:
                deposit_amount = pbrps.total_amount
            target_sheba = None
            if cafe.wallet.account_info:
                target_sheba = cafe.wallet.account_info.account_sheba_number

            invoice = wallet.deposit(amount=deposit_amount,
                                     fake=is_fake,
                                     cafepay_fee=_cafe.cafepay_fee,
                                     delivery_fee=delivery_fee,
                                     fee_payer=_cafe.fee_payer,
                                     tag=InvoiceConsts.PAY_PBR_SESSION,
                                     item=pbrps,
                                     payment_gate=_cafe.payment_gate,
                                     merchant=_cafe.merchant,
                                     use_default_gate=_cafe.use_default_gate,
                                     payment_session=payment_session,
                                     sub_payment_target_sheba=target_sheba,
                                     auto_clear=cafe.wallet.auto_clear,
                                     extra=_table)

            # add the invoice to the session
            pbrps.invoice = invoice
            pbrps.save()

            return pbrps


class PBRPaymentManualSessionCreateSerializer(serializers.ModelSerializer):
    payments = PBRPaymentCreateSerializer(many=True)

    class Meta:
        model = PBRPaymentSession
        fields = ['pk', 'payments', 'method']

    def validate_payments(self, payments):
        validate_distinct_payments(payments)

        errors = []

        cafe = get_object_or_404(Cafe, pk=self.context.get('view').kwargs.get('cafe_id'))

        for payment in payments:
            if payment.get('pbr').product.cafe != cafe:
                errors += [{'%d' % payment.get('pbr').pk:
                                _("Cafe mismatch")}]

        if errors:
            raise serializers.ValidationError({'payments': errors})

        return payments

    def create(self, validated_data):

        payments = validated_data.pop('payments')
        payment_method = validated_data.get('method')
        with transaction.atomic():
            payments = lock_payments(payments)
            # create the session
            pbrps = PBRPaymentSession.objects.create(is_manual=True, **validated_data)

            for payment in payments:
                PBRPayment.objects.create(session=pbrps, **payment)

                # select the pbr for update to avoid concurrent payments
                pbr = payment['pbr']

                # add an internal transaction
                wallet = pbr.product.cafe.wallet

                wallet.deposit(amount=payment.get('amount'),
                               status=InvoiceConsts.PAYED,
                               tag=InvoiceConsts.PAYED_FOR_PRODUCT,
                               method=payment_method,
                               item=pbr)

                if payment_method == InvoiceConsts.DISCOUNT:
                    # in case of a discount, refunds may be required
                    payment_info = pbr.payment_info
                    net_payed_amount = payment_info.get('net_payed_amount')
                    total_amount = payment_info.get('total_amount')

                    remaining = total_amount - payment.get('amount')  # total - discount

                    if net_payed_amount > remaining:
                        # refund net_payed_amount - remaining
                        pass
            return pbrps


class PBRAmountRefundSerializerBase(serializers.Serializer):
    pbr = serializers.PrimaryKeyRelatedField(queryset=ProductBillRelation.objects.all())
    amount = serializers.IntegerField()
    invoice = serializers.PrimaryKeyRelatedField(queryset=Invoice.objects.all())

    def validate(self, attrs):
        amount = attrs.get('amount')
        pbr = attrs.get('pbr')

        if amount <= 0 or amount > pbr.net_payed_amount:
            raise serializers.ValidationError({'amount': _("Amount must be between 0 and %d" % pbr.net_payed_amount)})

        invoice = attrs['invoice']
        if (not pbr.invoices.filter(pk=invoice.pk).exists() or
                invoice.status not in (InvoiceConsts.PAYED, InvoiceConsts.INTERNAL) or
                invoice.tag != InvoiceConsts.PAYED_FOR_PRODUCT):
            raise serializers.ValidationError({'invoice': _('Invoice does not belong to this payment')})
        expected_wallet = attrs['to'].wallet_id if 'to' in attrs else pbr.product.cafe.wallet_id
        expected_type = InvoiceConsts.WITHDRAW if 'to' in attrs else InvoiceConsts.DEPOSIT
        if invoice.wallet_id != expected_wallet or invoice.type != expected_type:
            raise serializers.ValidationError({'invoice': _('Refund recipient does not match the payment')})
        refunded = PBRRefund.objects.filter(invoice=invoice).aggregate(total=Sum('amount'))['total'] or 0
        if amount > invoice.amount - refunded:
            raise serializers.ValidationError({'amount': _('Exceeded refundable invoice amount')})
        return attrs


def validate_refund_batch(refunds):
    seen = set()
    totals = {}
    for refund in refunds:
        key = (refund['pbr'].pk, refund['invoice'].pk)
        if key in seen:
            raise serializers.ValidationError(_('Duplicate refund item'))
        seen.add(key)
        totals[key[0]] = totals.get(key[0], 0) + refund['amount']
    for refund in refunds:
        if totals[refund['pbr'].pk] > refund['pbr'].net_payed_amount:
            raise serializers.ValidationError(_('Exceeded refundable order amount'))


def lock_refunds(refunds):
    pbrs = {pbr.pk: pbr for pbr in ProductBillRelation.objects.select_for_update()
            .filter(pk__in=[refund['pbr'].pk for refund in refunds]).order_by('pk')}
    invoices = {invoice.pk: invoice for invoice in Invoice.objects.select_for_update()
                .filter(pk__in=[refund['invoice'].pk for refund in refunds]).order_by('pk')}
    locked = [dict(refund, pbr=pbrs[refund['pbr'].pk], invoice=invoices[refund['invoice'].pk])
              for refund in refunds]
    for refund in locked:
        PBRAmountRefundSerializerBase().validate(refund)
    validate_refund_batch(locked)
    return locked


class PBRAmountRefundSerializer(PBRAmountRefundSerializerBase):
    to = serializers.PrimaryKeyRelatedField(queryset=UserProfile.objects.all())


class PBRAmountInternalRefundSerializer(PBRAmountRefundSerializerBase):
    pass


class PBRRefundSerializerBase(serializers.Serializer):
    cafe = serializers.HiddenField(default=0)

    def validate_cafe(self, cafe):
        cafe = get_object_or_404(Cafe, pk=self.context.get('view').kwargs.get('cafe_id'))
        return cafe

    def validate(self, attrs):
        refunds = attrs.get('refunds')

        if not refunds:
            raise serializers.ValidationError(_("Empty refund not permitted"))

        errors = []

        cafe = attrs.get('cafe')

        for refund in refunds:
            if refund.get('pbr').product.cafe != cafe:
                errors += [{
                    'pbr':
                        _("Cafe mismatch")
                }]

        if errors:
            raise serializers.ValidationError({"refunds": errors})
        validate_refund_batch(refunds)
        return attrs


class PBRRefundSerializer(PBRRefundSerializerBase):
    refunds = PBRAmountRefundSerializer(many=True)


class PBRInternalRefundSerializer(PBRRefundSerializerBase):
    refunds = PBRAmountInternalRefundSerializer(many=True)


class PBRPaymentInvoicesSerializer(serializers.ModelSerializer):
    payment_invoices = PaymentInvoicesSerializer(read_only=True)

    class Meta:
        model = ProductBillRelation
        fields = ['pk', 'payment_invoices']


class PBRPaymentSerializer(serializers.ModelSerializer):
    owner = get_user_profile_basic_info_serializer()()
    datetime = serializers.DateTimeField(read_only=True, source='pbr.datetime')

    class Meta:
        model = PBRPayment
        fields = ['pk', 'pbr_str', 'owner', 'is_manual', 'datetime',
                  'amount', ]
