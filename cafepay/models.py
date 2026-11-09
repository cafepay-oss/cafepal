import datetime
import math
from math import floor, ceil
from uuid import uuid4

from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models, transaction, IntegrityError
from django.db.models import Q, Sum, Count, F
from django.db.models.expressions import RawSQL
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.functional import cached_property
from django.utils.translation import gettext as _
from location_field.models.plain import PlainLocationField
from rest_framework.authtoken.models import Token

from cafepay.api_v1.consts import (AccountInfoConsts, CharacterFieldConsts,
                                   DateTimeRangeConsts, InvoiceConsts, UserProfileConsts, CafeUserProfileRelationConsts)
from cafepay.api_v1.helpers import generate_code, send_verification_code, generate_table_token, APIBadRequest, \
    clean_null_values, get_payment_info, kavenegar_send_sms, datetime_to_local_str, SumDistinctHACK, notify_watchers
from cafepay.api_v1.modules.payment.payment_gates import pg_gates
from cafepay.receipt_storage import PrivateReceiptStorage


class UserProfile(models.Model):
    """
        User Profile object, one to one with django user
        additional info about the user
    """

    django_user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="user_profile")
    is_elevated_user = models.BooleanField(default=False)

    first_name = models.CharField(max_length=255, default="")
    last_name = models.CharField(max_length=255, default="")

    card_number = models.CharField(max_length=16, blank=True, null=True)

    private_id = models.UUIDField(default=uuid4, unique=True)

    address = models.CharField(max_length=1024, blank=True, null=True)

    active_address = models.ForeignKey("UserProfileAddress", on_delete=models.SET_NULL, blank=True, null=True)

    phone_number = models.CharField(max_length=12, validators=[
        RegexValidator(
            regex=r"^(\+98|0)?9\d{9}$",
            message=_("Enter a valid phone number"),
            code='invalid_phone_number'
        ),
    ], unique=True)

    email = models.EmailField(max_length=255, blank=True, null=True)

    national_code = models.CharField(max_length=15, blank=True, null=True)

    wallet = models.OneToOneField("Wallet", on_delete=models.PROTECT, related_name="user_profile")

    verification_status = models.CharField(max_length=1, choices=UserProfileConsts.states,
                                           default=UserProfileConsts.PENDING)

    @property
    def base_addresses(self):
        return self.addresses.filter(is_clone=False)

    @property
    def balance(self) -> int:
        return self.wallet.balance

    @property
    def has_usable_password(self):
        return self.django_user.has_usable_password()

    @property
    def token(self):
        token, created = Token.objects.get_or_create(user=self.django_user)
        return token.key

    @property
    def full_name(self):
        return self.first_name + " " + self.last_name

    @property
    def date_joined(self):
        return self.django_user.date_joined

    @property
    def active_preorder(self):
        pbr = ProductBillRelation.objects.filter(
            ~Q(status=ProductBillRelation.DELIVERED),
            Q(bill__join__sent=False),
            Q(bill__join__force_close=False),
            bill__table__table_type=TableToken.SELF_PICKUP,
            user_profile=self).first()
        if pbr:
            return pbr.bill.table.uuid
        return None

    @property
    def cafe_relations_no_sms(self):
        return self.cafe_relations.exclude(role__code_name="PAYMENT_NOTIFY")

    def __str__(self):
        return "%s (%s)" % (self.django_user.username, self.full_name)


class UserProfilePhoneVerificationObjectManager(models.Manager):
    def create(self, **kwargs):
        created = False

        with transaction.atomic():
            user_profile = kwargs.get('user_profile')

            # lock the user profile to prevent concurrent creations
            user_profile = UserProfile.objects.select_for_update().get(pk=user_profile.pk)

            time = timezone.now() - timezone.timedelta(minutes=UserProfilePhoneVerification.RETRY_TIME)

            # select the latest valid user profile phone verification object
            user_profile_phone = UserProfilePhoneVerification.objects.order_by('-create_date'). \
                filter(create_date__gte=time,
                       user_profile__phone_number=user_profile.phone_number) \
                .first()

            # create a new object if none exists
            if not user_profile_phone:
                self.filter(user_profile=user_profile, used=False).update(burnt=True)
                obj = UserProfilePhoneVerification(**kwargs)
                obj.save()
                created = True

        if created:
            return {'status': 201, 'obj': obj}

        return {
            'status': 403,
            'wait': timezone.timedelta(minutes=UserProfilePhoneVerification.RETRY_TIME) +
                    (user_profile_phone.create_date - timezone.now())}


    def consume(self, phone, code):
        """Serialize attempts, expiry checks, and single-use code consumption."""
        with transaction.atomic():
            profile = UserProfile.objects.select_for_update().filter(phone_number=phone).first()
            if not profile:
                return {'status': 404}
            cutoff = timezone.now() - timezone.timedelta(minutes=UserProfilePhoneVerification.VALIDITY_TIME)
            verification = self.select_for_update().filter(
                user_profile=profile, create_date__gte=cutoff, used=False, burnt=False,
                query_times__lt=UserProfilePhoneVerification.MAX_QUERY).order_by('-create_date', '-pk').first()
            if not verification:
                return {'status': 404}
            if not constant_time_compare(str(code or ''), verification.code):
                verification.query_times += 1
                verification.save(update_fields=['query_times'])
                return {'status': 403, 'allowed_retry_times':
                        UserProfilePhoneVerification.MAX_QUERY - verification.query_times}
            profile.verification_status = UserProfileConsts.VERIFIED
            profile.save(update_fields=['verification_status'])
            Token.objects.get_or_create(user=profile.django_user)
            verification.used = True
            verification.save(update_fields=['used'])
            self.filter(user_profile=profile, used=False).update(burnt=True)
            return {'status': 200, 'profile': profile}


class UserProfilePhoneVerification(models.Model):
    """
        Used for phone verification by sms
        auto generates a 5 digit code
        limits select querying
        time intervals between consecutive creation
    """

    RETRY_TIME = 1
    VALIDITY_TIME = 5
    MAX_QUERY = 5

    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="phone_numbers")
    code = models.CharField(max_length=13, default=generate_code)
    create_date = models.DateTimeField(auto_now_add=True)
    query_times = models.IntegerField(default=0)
    used = models.BooleanField(default=False)
    burnt = models.BooleanField(default=False)

    objects = UserProfilePhoneVerificationObjectManager()


@receiver(post_save, sender=UserProfilePhoneVerification)
def send_verification_sms(sender, instance, created, **kwargs):
    """
        send the verification code if a new object is created
    """

    if created:
        send_verification_code(instance.user_profile.phone_number, instance.code)


class AccountInfo(models.Model):
    """
        Banking Account Information
    """

    account_holder_name = models.CharField(max_length=255, blank=True, null=True)
    account_holder_last_name = models.CharField(max_length=255, blank=True, null=True)

    account_number = models.CharField(max_length=255, blank=True, null=True)
    account_sheba_number = models.CharField(max_length=255, blank=True, null=True)

    verification_status = models.CharField(max_length=1, choices=AccountInfoConsts._account_verification_states,
                                           default=AccountInfoConsts.PENDING)


class Wallet(models.Model):
    """
        An E-Wallet used as a holder for transactions belonging to an account
    """
    # [ ] todo stack trace log on exceptions

    account_info = models.OneToOneField(AccountInfo, on_delete=models.SET_NULL, blank=True, null=True)
    auto_clear = models.BooleanField(default=False)

    @property
    def owner_string(self):
        try:
            return str(UserProfile.objects.get(wallet=self).full_name)
        except UserProfile.DoesNotExist:
            try:
                return str(Cafe.objects.get(wallet=self).name)
            except Cafe.DoesNotExist:
                return "N/A"

    @property
    def balance(self):

        with transaction.atomic():
            # lock the current wallet

            wallet = Wallet.objects.select_for_update().get(pk=self.pk)

            debit_credit_sum = wallet.invoice.filter(Q(status=InvoiceConsts.PAYED) |
                                                     Q(status=InvoiceConsts.INTERNAL)).exclude(fake=True). \
                values("type").annotate(bal=F("amount") + F("delivery_fee")).annotate(Sum("bal"))

            net = 0
            for t in debit_credit_sum:
                if t['type'] == InvoiceConsts.DEPOSIT:
                    net += t['bal__sum']
                elif t['type'] == InvoiceConsts.WITHDRAW:
                    net -= t['bal__sum']

            return net

    @property
    def total_income_invoices(self):
        wallet = self
        income_invoices = wallet.invoice.filter((Q(status=InvoiceConsts.PAYED) |
                                                 Q(status=InvoiceConsts.INTERNAL)) &
                                                Q(type=InvoiceConsts.DEPOSIT))
        return income_invoices

    def deposit(self, amount, **kwargs):
        """
            shortcut for deposit invoice creation on a wallet
            amount: amount to deposit
            status: status to create the invoice with
        """

        with transaction.atomic():
            # lock the Wallet
            wallet = Wallet.objects.select_for_update().get(pk=self.pk)

            # create the invoice
            return Invoice.objects.create(amount=amount,
                                          wallet=wallet,
                                          type=InvoiceConsts.DEPOSIT,
                                          **kwargs)

    def withdraw(self, amount, **kwargs):
        """
            shortcut for withdraw invoice creation on a wallet
            amount: amount to withdraw
            status: status to create the invoice with
        """

        with transaction.atomic():
            # lock the Wallet
            wallet = Wallet.objects.select_for_update().get(pk=self.pk)

            # check for sufficient balance
            if wallet.balance >= amount:
                return Invoice.objects.create(amount=amount,
                                              wallet=wallet,
                                              type=InvoiceConsts.WITHDRAW,
                                              **kwargs)
            return None

    def transfer(self, amount, to: "Wallet", **kwargs):
        """

        :param amount:
        :param to: wallet to transfer to
        :return:
        """

        with transaction.atomic():
            # Opposite transfers must acquire the same pair in the same order.
            list(Wallet.objects.select_for_update().filter(pk__in=[self.pk, to.pk]).order_by('pk'))
            w = self.withdraw(amount=amount, **kwargs)

            if not w:
                return None

            d = to.deposit(amount=amount, **kwargs)

            return w, d


class CafeWallet(models.Model):
    """
    A users profile wallet in a specific cafe
    """

    wallet = models.ForeignKey(Wallet, related_name="cafe_wallet", on_delete=models.CASCADE)
    user_profile = models.ForeignKey(UserProfile, related_name="cafe_wallet", on_delete=models.CASCADE)
    cafe = models.ForeignKey("Cafe", related_name="cafe_wallet", on_delete=models.CASCADE)

    @staticmethod
    def get_or_create(user_profile, cafe):
        with transaction.atomic():
            # Serialize first use without creating an orphan wallet on conflicts.
            UserProfile.objects.select_for_update().get(pk=user_profile.pk)
            try:
                return CafeWallet.objects.select_related('wallet').get(user_profile=user_profile, cafe=cafe)
            except CafeWallet.DoesNotExist:
                return CafeWallet.objects.create(user_profile=user_profile, cafe=cafe,
                                                 wallet=Wallet.objects.create())

    class Meta:
        unique_together = ['user_profile', 'cafe']


class PaymentSession(models.Model):
    datetime = models.DateTimeField(auto_now_add=True)


class Invoice(models.Model):
    """
        Holding information about a transaction
    """

    payment_session = models.ForeignKey(PaymentSession, related_name="invoices", blank=True, null=True,
                                        on_delete=models.PROTECT)

    uuid = models.UUIDField(default=uuid4)

    amount = models.PositiveIntegerField()
    fake = models.BooleanField(default=False)  # used in internal verification process

    cafepay_fee = models.FloatField(default=0)
    fee_payer = models.BooleanField(default=False)

    delivery_fee = models.IntegerField(default=0)

    type = models.CharField(max_length=1, choices=InvoiceConsts.balance_types)
    status = models.CharField(max_length=1, choices=InvoiceConsts.states, default=InvoiceConsts.CREATED)
    create_datetime = models.DateTimeField(auto_now_add=True)
    last_payment_timestamp = models.DateTimeField(blank=True, null=True)
    refund_attempt_timestamp = models.DateTimeField(blank=True, null=True)

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="invoice")

    tag = models.CharField(max_length=1, choices=InvoiceConsts.tags)

    method = models.CharField(max_length=1, choices=InvoiceConsts.methods, default=InvoiceConsts.ONLINE)

    # item this invoice is for
    # invoice without item may also exist
    # ex: charge wallet invoices don't need an item

    item_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, blank=True, null=True)
    item_id = models.PositiveIntegerField(blank=True, null=True)

    item = GenericForeignKey('item_content_type', 'item_id')

    # extra data that might be of interest about this invoice
    # ex: PBRRefund of a refund invoice
    extra_content_type = models.ForeignKey(ContentType, related_name="extra",
                                           on_delete=models.CASCADE, blank=True, null=True)
    extra_id = models.PositiveIntegerField(blank=True, null=True)
    extra = GenericForeignKey('extra_content_type', 'extra_id')

    token = models.CharField(max_length=100, default="", blank=True, null=True)
    transId = models.CharField(max_length=100, default="", blank=True, null=True)
    card_number = models.CharField(max_length=100, default="", blank=True, null=True)

    callback_url = models.URLField(blank=True, null=True)

    use_default_gate = models.BooleanField(default=False)

    payment_gate = models.CharField(max_length=10, choices=pg_gates, blank=True, null=True)
    merchant = models.CharField(max_length=1024, blank=True, null=True)

    sub_payment_target_sheba = models.CharField(max_length=100, blank=True, null=True)
    auto_clear = models.BooleanField(default=False)


class CharacterField(models.Model):
    """
        Raw character field with a type classification
    """

    title = models.CharField(max_length=255)
    description = models.CharField(max_length=1000, blank=True, null=True)

    type = models.CharField(max_length=10, choices=CharacterFieldConsts.types)
    staff = models.ForeignKey(UserProfile, related_name="categories", on_delete=models.PROTECT, null=True, blank=True)
    cafe = models.ForeignKey("Cafe", on_delete=models.CASCADE, related_name="character_field", null=True, blank=True)

    order = models.IntegerField(default=0)

    is_delete = models.BooleanField(default=False)
    menu = models.ForeignKey("Menu", blank=True, null=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.title


class DateTimeRange(models.Model):
    """
        day: eg. monday
        star time: eg. 13
        end time: eg 24
    """

    day = models.CharField(max_length=10, choices=DateTimeRangeConsts.days)
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return self.day


class CafeDocumentType(models.Model):
    doc_type = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)

    def __str__(self):
        return self.doc_type


class CafeDocument(models.Model):
    document_type = models.ForeignKey(CafeDocumentType, on_delete=models.PROTECT)
    document = models.FileField(max_length=255)

    cafe = models.ForeignKey("Cafe", on_delete=models.CASCADE, related_name="documents")

    def __str__(self):
        return str(self.document_type)


class CafeUserProfileRelationRole(models.Model):
    display_name = models.CharField(max_length=200)
    code_name = models.CharField(max_length=20)
    cafe = models.ForeignKey("Cafe", related_name='staff_roles', on_delete=models.CASCADE)

    class Meta:
        unique_together = [['code_name', 'cafe']]

    def __str__(self):
        return "cafe: %d, role: %s" % (self.cafe.pk, self.display_name)


class CafeUserProfileRelation(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='cafe_relations')
    role = models.ForeignKey(CafeUserProfileRelationRole, on_delete=models.PROTECT, related_name='cafe_relations')
    status = models.CharField(max_length=1, choices=CafeUserProfileRelationConsts.states,
                              default=CafeUserProfileRelationConsts.PENDING)

    class Meta:
        unique_together = [['user_profile', 'role']]

    @staticmethod
    def get_active_user_cafes(user_profile):
        return [cup.cafe for
                cup in
                CafeUserProfileRelation.objects.filter(user_profile=user_profile,
                                                       status=CafeUserProfileRelationConsts.VERIFIED)
                ]


class PrinterType(models.Model):
    """Printer types"""
    KITCHEN = "0"
    CUSTOMER = "1"

    printer_types = ((KITCHEN, _("Kitchen")),
                     (CUSTOMER, _("Customer")))

    type = models.CharField(max_length=1, default=CUSTOMER, choices=printer_types)


class Printer(models.Model):
    """A printer in cafe"""

    name = models.CharField(max_length=100)

    display_name = models.CharField(max_length=100)

    uid = models.CharField(max_length=100)
    cafe = models.ForeignKey("Cafe", related_name="printers", on_delete=models.CASCADE)
    types = models.ManyToManyField(PrinterType, related_name="printers", blank=True)
    width = models.CharField(max_length=100, default="8cm")
    is_on = models.BooleanField(default=True)
    description = models.CharField(max_length=1024, blank=True, null=True)

    groups = models.ManyToManyField(CharacterField,
                                    limit_choices_to={'type': CharacterFieldConsts.GROUP},
                                    blank=True)

    ONE_PAGE = "0"
    GROUPED = "1"

    policies = (
        (ONE_PAGE, _("One page")),
        (GROUPED, _("Grouped"))
    )

    policy = models.CharField(max_length=1, choices=policies, default=ONE_PAGE)

    @property
    def active_jobs(self):
        return self.jobs.filter(is_done=False)


class PrinterJob(models.Model):
    """A printer job"""
    printer = models.ForeignKey(Printer, related_name='jobs', on_delete=models.CASCADE)
    raw_data = models.CharField(max_length=10000)

    is_done = models.BooleanField(default=False)

    description = models.CharField(max_length=1024, blank=True, null=True)


class PushEndpoint(models.Model):
    text = models.CharField(max_length=4096)
    keys = models.CharField(max_length=4096)
    cafe = models.ForeignKey("Cafe", related_name="push_endpoints", on_delete=models.CASCADE)


class Cafe(models.Model):
    """
        Cafe
    """

    name = models.CharField(max_length=200, verbose_name=_("name"))
    description = models.CharField(max_length=5000, blank=True, verbose_name=_("description"))

    location = PlainLocationField(based_fields=['city'], zoom=7, verbose_name=_("location"), blank=True, null=True)
    address = models.CharField(max_length=255, verbose_name=_("address"))

    menu_prices_on = models.BooleanField(default=False)
    menu_items_on = models.BooleanField(default=False)

    phone = models.CharField(max_length=255, blank=True, null=True)
    working_times = models.CharField(max_length=255, blank=True, null=True)

    is_menu_only = models.BooleanField(default=False)

    is_closed = models.BooleanField(default=False)
    instagram = models.CharField(max_length=255, blank=True, null=True)

    open_times = models.ManyToManyField(DateTimeRange, blank=True)

    wallet = models.OneToOneField(Wallet, on_delete=models.CASCADE, related_name="shop_wallet")

    cafepay_fee = models.FloatField(default=0.02)
    fee_payer = models.BooleanField(default=False)
    buffer_in_minutes = models.IntegerField(default=15)

    username = models.CharField(max_length=255, blank=True, null=True, unique=True)

    short_description = models.CharField(max_length=1024, blank=True, null=True)

    mean_ready_duration = models.DurationField(default=datetime.timedelta(minutes=35))

    payment_first = models.BooleanField(default=False)
    payment_only = models.BooleanField(default=False)
    has_delivery = models.BooleanField(default=False)

    card_transfer_enabled = models.BooleanField(default=False)
    card_transfer_number = models.CharField(max_length=16, blank=True, default='')
    card_transfer_holder = models.CharField(max_length=100, blank=True, default='')

    has_first_time_offer = models.BooleanField(default=False)
    first_time_offer_amount = models.IntegerField(default=0)

    is_demo = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    delivery_fee = models.IntegerField(default=0)

    use_default_gate = models.BooleanField(default=False)

    payment_gate = models.CharField(max_length=10, choices=pg_gates, blank=True, null=True)
    merchant = models.CharField(max_length=1024, blank=True, null=True)

    def get_or_create_token(self, token_type):
        token = TableToken.objects.filter(cafe=self, type=token_type).order_by('pk').first()
        if token or token_type in (TableToken.SELF_PICKUP, TableToken.NORMAL):
            return token
        with transaction.atomic():
            # Legacy cafes retain lazy provisioning. Serialize concurrent first reads.
            Cafe.objects.select_for_update().get(pk=self.pk)
            token = TableToken.objects.filter(cafe=self, type=token_type).order_by('pk').first()
            if token:
                return token
            table = Table.objects.create(number=token_type, cafe=self,
                                         uuid=uuid4(), table_type=token_type)
            return TableToken.objects.create(cafe=self, type=token_type,
                                             status=TableToken.ACTIVE, table=table)

    @property
    def menu_only_token(self):
        return self.get_or_create_token(token_type=TableToken.MENU_ONLY)

    @property
    def preorder_token(self):
        return self.get_or_create_token(token_type=TableToken.SELF_PICKUP)

    @property
    def is_onsite(self):
        return not not self.get_or_create_token(token_type=TableToken.NORMAL)

    def get_mean_ready_time_from_now(self):
        return timezone.now() + self.mean_ready_duration

    def notify_payments(self, session, date_time):
        amount = session.total_amount

        # payments must have happened on the same table so one notification request suffices
        payment = session.payments.first()
        pbr = payment.pbr
        notify_watchers(pbr.bill.table)

        try:
            notify_role = self.staff_roles.get(code_name="PAYMENT_NOTIFY")
            all_staff = notify_role.cafe_relations.all()

            for staff in all_staff:
                from persiantools.jdatetime import JalaliDateTime
                kavenegar_send_sms('onlineorder', {
                    'token': "%dتومان" % int(amount),
                    'token2': datetime_to_local_str(date_time)
                }, staff.user_profile.phone_number)
        except CafeUserProfileRelationRole.DoesNotExist:
            pass

    @property
    def phones(self):
        return self.character_field.filter(type=CharacterFieldConsts.PHONE)

    @property
    def emails(self):
        return self.character_field.filter(type=CharacterFieldConsts.EMAIL)

    @property
    def total_deposits(self):
        return self.wallet.invoice.filter(type=InvoiceConsts.DEPOSIT)

    @property
    def total_online_deposits(self):
        return self.total_deposits.filter(method=InvoiceConsts.ONLINE)

    @property
    def total_refunds(self):
        return self.wallet.invoice.filter(tag=InvoiceConsts.REFUND, type=InvoiceConsts.WITHDRAW)

    @property
    def total_cleared(self):
        return self.wallet.invoice.filter(type=InvoiceConsts.CLEARING, tag=InvoiceConsts.CLEARING_TAG)

    @property
    def _to_be_cleared(self):

        # aggregate invoices
        deposits_amount = self.total_online_deposits.aggregate(total_amount=Sum('amount'))
        refunds_amount = self.total_refunds.aggregate(total_amount=Sum('amount'))
        total_cleared_amount = self.total_cleared.aggregate(total_amount=Sum('amount'))

        # clean them
        clean_null_values(deposits_amount)
        clean_null_values(refunds_amount)
        clean_null_values(total_cleared_amount)

        # total_online - (total_refund + total_cleared)
        amount = deposits_amount.get('total_amount') - (refunds_amount.get('total_amount') +
                                                        total_cleared_amount.get('total_amount'))
        return amount

    @property
    def to_be_cleared(self):
        return '{:,}'.format(self._to_be_cleared)

    @property
    def _to_be_cleared_net_amount(self):
        _to_be_cleared = self._to_be_cleared

        if self.fee_payer:
            _to_be_cleared_net = _to_be_cleared * (1 - self.cafepay_fee)
        else:
            _to_be_cleared_net = _to_be_cleared

        return _to_be_cleared_net

    @property
    def to_be_cleared_net(self):
        return '{:,}'.format(int(self._to_be_cleared_net_amount))

    @property
    def _total_deposits_amount(self):
        amount = self.total_deposits.aggregate(amount=Sum('amount')).get('amount')

        if not amount:
            amount = 0

        return amount

    @property
    def _total_online_deposits_amount(self):
        amount = self.total_online_deposits.aggregate(amount=Sum('amount')).get('amount')

        if not amount:
            amount = 0
        return amount

    @property
    def total_deposits_amount(self):
        return '{:,}'.format(self._total_deposits_amount)

    @property
    def total_online_deposits_amount(self):
        return '{:,}'.format(self._total_online_deposits_amount)

    @property
    def total_remaining(self):
        total = self._total_online_deposits_amount
        amount = self.wallet.invoice.filter(type=InvoiceConsts.CLEARING).aggregate(amount=Sum('amount')).get('amount')
        if not amount:
            amount = 0

        remaining = total - amount
        return '{:,}'.format(remaining)

    @staticmethod
    def get_group_name(cafe_id, content_type):
        # return group name by id
        return "cafe_%d" % int(cafe_id)

    @property
    def overall_rating(self):
        all_product_overall_ratings = [p.overall_rating['rate'] for p in self.products.all()]
        count = len(all_product_overall_ratings)

        if all_product_overall_ratings:
            return {
                'rate': sum(all_product_overall_ratings) / len(all_product_overall_ratings),
                'count': count
            }

        return {'rate': 0, 'count': 0}

    @property
    def avatar(self) -> models.ImageField:
        gallery_image = self.shop_images.filter(is_avatar=True).first()

        if not gallery_image:
            return None

        return gallery_image.image

    @property
    def is_open(self):
        return True

    @property
    def header_image(self) -> models.ImageField:
        gallery_image = self.shop_images.filter(is_header=True).first()

        if not gallery_image:
            return None

        return gallery_image.image

    @property
    def shop_images_filtered(self):
        return self.shop_images.all()

    @property
    def customers(self):
        # list of all cafe users
        # people who made payments
        # and people who added products

        """
            List of cafe users is defined as:

            A = ProductBillRelations ->
            user_profile (people who added products on the cafe tables)

            B = PBRPaymentsSessions Of those ProductBillRelations ->
            user_profiles (people who made payments in the cafe)

            C = A | B

            users_list = C.distinct()
        """

        pbrs = ProductBillRelation.objects.filter(bill__table__cafe=self).distinct()
        pbrs_user_profiles = UserProfile.objects.filter(private_id__in=pbrs.values('user_profile')).distinct()

        # get All pbr payments
        pbr_payments = PBRPayment.objects.filter(pbr__in=pbrs).distinct()

        # get all pbr payment sessions
        pbr_payment_sessions = PBRPaymentSession.objects.filter(payments__in=pbr_payments).distinct()
        pbr_payment_session_user_profile = UserProfile.objects.filter(pbr_payments__in=pbr_payment_sessions).distinct()

        user_profiles = pbrs_user_profiles | pbr_payment_session_user_profile
        user_profiles = user_profiles.distinct()

        return user_profiles

    @property
    def products_ordered(self):
        return self.products.order_by('order')

    @property
    def categories_ordered(self):
        return self.character_field.filter(type=CharacterFieldConsts.CATEGORY)

    def customer_summary(self, customer, many=False):
        """
        :param customer:
        :param many:
        :return: financial summary of the customer in this cafe
            - total spent
            - total involved
            - total times ordered
            - average spent
            - favorite product
            - todo: total spent on favorite product
            - todo: times ordered last week
            - todo: times ordered last month
        """

        # total spent: total amount of deposit invoices of
        # the customers wallet that
        # their item is one of this cafe's products
        if not many:
            customer_wallet = [customer.wallet, ]
            customer = [customer, ]
        else:
            customer_wallet = Wallet.objects.filter(user_profile__in=customer).distinct()

        # total amount -- start
        invoices = Invoice.objects.filter(
            wallet__in=customer_wallet,
            type=InvoiceConsts.WITHDRAW,
            pbr__product__in=self.products.all()
        ).distinct()

        summary = {}
        total_amount_dict = invoices.aggregate(total_amount=SumDistinctHACK('amount'))

        summary['total_amount'] = total_amount_dict['total_amount']
        # total amount -- end

        # total times ordered -- start
        total_times_ordered = TableJoin.objects.filter(
            bills__bill_pbrs__product__in=self.products.all(),
            bills__bill_pbrs__user_profile__in=customer
        ).distinct().aggregate(total_times=Count('pk', distinct=True))
        summary['total_times_ordered'] = total_times_ordered['total_times']
        # total times ordered -- end

        # average amount spent -- start
        clean_null_values(summary)

        if summary['total_times_ordered'] == 0:
            summary['average_amount'] = 0
        else:
            summary['average_spent'] = math.ceil(summary['total_amount'] /
                                                 summary['total_times_ordered'])
        # average amount spent -- end

        # favorite product -- start
        products_count = ProductBillRelation.objects.filter(product__in=self.products.all(),
                                                            user_profile__in=customer).distinct().values('product') \
            .annotate(total_sum=SumDistinctHACK('count'))

        products_count_list = list(products_count)

        for product_count in products_count_list:
            clean_null_values(product_count)

        def get_key(product_count_element):
            return product_count_element['total_sum']

        if products_count_list:
            fav_product_count = max(products_count_list, key=get_key)
            fav_product = Product.objects.get(pk=fav_product_count['product'])

            summary['fav_product'] = fav_product.name
        else:
            summary['fav_product'] = 'N/A'
        # favorite product -- end
        return summary

    def __str__(self):
        return str(self.pk) + "-" + self.name


class Gallery(models.Model):
    """
        Gallery belonging to a shop
    """

    image = models.ImageField()

    # the worst database design decision in the history of softwre engeering
    is_avatar = models.BooleanField(default=False)
    is_header = models.BooleanField(default=False)
    is_qr = models.BooleanField(default=False)

    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name="shop_images", blank=False)


class Menu(models.Model):
    """
        For classification of products into a single menu
    """

    name = models.CharField(max_length=20)
    is_active = models.BooleanField(default=False)

    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name="menus")
    products = models.ManyToManyField("Product", related_name="menu", blank=True)
    staff = models.ForeignKey(UserProfile, related_name="menu_manage", on_delete=models.PROTECT)

    @property
    def categories(self):
        return CharacterField.objects.filter(type=CharacterFieldConsts.CATEGORY,
                                             products__in=self.products.all()).distinct().order_by('order')

    @property
    def not_deleted_categories(self):
        return self.categories.filter(is_delete=False)

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    """
        An image for a product
    """

    image = models.ImageField(max_length=255)
    caption = models.CharField(max_length=100, blank=True, null=True)
    product = models.ForeignKey("Product", related_name="images", on_delete=models.CASCADE)

    is_avatar = models.BooleanField(default=False)

    def __str__(self):
        return str(self.image)


class Product(models.Model):
    """
        A product or service that the cafe provides
        this is immutable
        changes and deletions yeald new products: Deprecated (maybe)
    """

    name = models.CharField(max_length=200)
    description = models.CharField(max_length=255, blank=True, null=True)

    original_price = models.PositiveIntegerField()
    discount = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])

    available = models.BooleanField(default=True)
    count = models.IntegerField(default=0)
    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name="products", blank=False, null=False)
    category = models.ForeignKey(CharacterField, limit_choices_to={'type': CharacterFieldConsts.CATEGORY},
                                 on_delete=models.PROTECT,
                                 related_name="products")

    group = models.ForeignKey(CharacterField, limit_choices_to={'type': CharacterFieldConsts.GROUP},
                              on_delete=models.SET_NULL,
                              blank=True, null=True,
                              related_name="group_products")

    staff = models.ForeignKey(UserProfile, related_name="products", on_delete=models.PROTECT)

    is_delete = models.BooleanField(default=False)

    order = models.IntegerField(default=0)

    @property
    def remaining(self):
        return self.count

    def payment_info_timed(self, start_date, end_date, start_time, end_time):
        """payment info of all PBRs of the current product"""
        pbrs = ProductBillRelation.objects.filter(product=self,
                                                  datetime__date__gte=start_date,
                                                  datetime__date__lte=end_date,
                                                  datetime__time__gte=start_time,
                                                  datetime__time__lte=end_time)
        return get_payment_info(pbrs)

    @property
    def price(self) -> models.IntegerField:
        return self.original_price * (100 - self.discount) // 100

    @property
    def valid_comment_ratings(self):
        return self.comments.filter(status=ProductRatingComment.ACCEPTED).order_by(
            'commenter',
            '-id'
        ).distinct('commenter')

    @property
    def overall_rating(self):
        ratings = self.comments.filter(status=ProductRatingComment.ACCEPTED).order_by(
            'commenter',
            '-id'
        ).values_list('rate', flat=True).order_by('commenter', '-pk').distinct('commenter')

        count = len(ratings)

        if ratings:
            return {
                'rate': sum(ratings) / count,
                'count': count
            }

        return {'rate': 0, 'count': 0}

    @property
    def payment_info(self):
        _pbrs = ProductBillRelation.objects.filter(product=self)
        return get_payment_info(_pbrs)

    def __str__(self):
        return self.name


class ProductRatingComment(models.Model):
    """
        Comment and rating on a product
    """

    PENDING = '0'
    ACCEPTED = '1'

    states = ((PENDING, _("Pending")),
              (ACCEPTED, _("Accepted")))

    commenter = models.ForeignKey(UserProfile, related_name="product_comments", on_delete=models.CASCADE)
    rate = models.IntegerField(default=0, validators=[
        MinValueValidator(0),
        MaxValueValidator(5)
    ])
    comment = models.TextField(max_length=1000)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='comments')
    status = models.CharField(choices=states, max_length=1, default=PENDING)

    @property
    def is_valid(self):
        return not ProductRatingComment.objects.filter(Q(product=self.product) &
                                                       Q(commenter=self.commenter) &
                                                       Q(pk__gt=self.pk)).exists()


class Bill(models.Model):
    """
        A bill is generated for a table
        if a bill has a pre bill, it means it has been transferred from another table
    """

    table = models.ForeignKey('Table', on_delete=models.PROTECT, related_name="bills")
    pre_bill = models.ManyToManyField('Bill', blank=True)
    join = models.ForeignKey('TableJoin', on_delete=models.PROTECT,
                             related_name="bills",
                             blank=True, null=True)

    def ensure_receipt_order_editable(self):
        owner = self.current_owner or self
        if owner.join_id and owner.join.card_transfers.filter(status__in=['submitted', 'confirmed', 'rejected']).exists():
            raise APIBadRequest('این سفارش با رسید ثبت شده است و اقلام آن قابل تغییر نیست.')

    def add_product(self, product, user_profile, pickup_time, is_staff, quantity=1):
        """
            Create an object of ProductBillRelation model
        """

        self.ensure_receipt_order_editable()
        # if there is an existing pbr matching the given user_profile and is_staff
        # update the existing pbr
        try:
            pbr = ProductBillRelation.objects.select_for_update().get(
                status__in=[ProductBillRelation.PENDING, ProductBillRelation.ACCEPTED],
                bill=self,
                product=product, is_staff=is_staff,
                user_profile=user_profile)

        # create new pbr object according to user_profile and is_staff
        except ProductBillRelation.DoesNotExist:
            with transaction.atomic():
                pbr = ProductBillRelation.objects.create(**{
                    'bill': self,
                    'product': product,
                    'pickup_time': pickup_time,
                    'original_price': product.original_price,
                    'discount': product.discount,
                    "user_profile": user_profile,
                    'is_staff': is_staff
                })

        with transaction.atomic():
            # update
            pbr.count += quantity
            product.count -= quantity

            # save
            product.save()
            pbr.save()

    def remove_product(self, product, user_profile, is_staff, is_actor_staff, quantity=1):
        """
            remove one instance of the given product from products of this bill
        """
        self.ensure_receipt_order_editable()
        try:
            with transaction.atomic():
                get_kwargs = {
                    'status__in': [ProductBillRelation.PENDING,
                                   ProductBillRelation.ACCEPTED],
                    'bill': self,
                    'product': product,
                    'is_staff': is_staff,
                    'user_profile': user_profile
                }

                # staff may remove pbr that's already sent to kitchen
                if is_actor_staff:
                    get_kwargs['status__in'].append(ProductBillRelation.KITCHEN)

                pbr = ProductBillRelation.objects.select_for_update().get(**get_kwargs)

                # number of items that have no payments
                # ex: 3 espresso at 5$ - if 2$ payed=> not_paid = 2
                # ex: 3 espresso at 5$ - if 12$ payed=> not_paid = 0
                not_paid = pbr.count - pbr.items_payed

                with transaction.atomic():
                    if not_paid >= quantity and pbr.count >= quantity:
                        # update
                        pbr.count -= quantity
                        product.count += quantity

                        # save
                        product.save()
                        pbr.save()
                    else:
                        raise APIBadRequest(_("You cannot delete a product that you already made payments on"))

                # clear the pbr object if it's count is 0
                if pbr.count <= 0:
                    try:
                        pbr.delete()
                    except IntegrityError:
                        pass

                return True
        except ProductBillRelation.DoesNotExist:
            raise APIBadRequest(_('Product is not in the active bill'))

    @property
    def all_products(self):
        """
            List of all products on this bill and all product of all pre_bills
        """

        return ProductBillRelation.objects.filter(bill_id__in=self.related_bill_ids('id', self.pk))

    @classmethod
    def related_bill_ids(cls, field, value, ancestors=False):
        """Follow legacy bill links once, without crossing cafes or live orders.

        The legacy self-M2M stores symmetric links. UNION terminates cycles.
        Descendants include detached bills; ancestors stop at the first owner.
        """
        if field not in ('id', 'join_id'):
            raise ValueError('Unsupported bill lookup')
        relation = cls._meta.get_field('pre_bill')
        source = relation.m2m_field_name() + '_id'
        target = relation.m2m_reverse_field_name() + '_id'
        if ancestors:
            source, target = target, source
        query = """WITH RECURSIVE linked(id, cafe_id, join_id) AS (
            SELECT b.id, t.cafe_id, b.join_id
            FROM {bill} b JOIN {table} t ON t.id = b.table_id
            WHERE b.{field} = %s
            UNION
            SELECT child.id, linked.cafe_id, child.join_id
            FROM linked JOIN {relation} edge ON edge.{source} = linked.id
            JOIN {bill} child ON child.id = edge.{target}
            JOIN {table} t ON t.id = child.table_id
            WHERE t.cafe_id = linked.cafe_id AND {condition}
        ) SELECT id FROM linked""".format(
            bill=cls._meta.db_table, table=Table._meta.db_table,
            relation=relation.remote_field.through._meta.db_table,
            source=source, target=target, field=field,
            condition='linked.join_id IS NULL' if ancestors else 'child.join_id IS NULL')
        return RawSQL(query, [value])

    @property
    def current_owner(self):
        """Return the active destination bill for a transferred order."""
        if self.join_id:
            return None if self.is_closed else self
        owners = list(Bill.objects.filter(
            pk__in=self.related_bill_ids('id', self.pk, ancestors=True),
            join__force_close=False, join__sent=False).select_related('join', 'table').order_by('pk'))
        if len({bill.join_id for bill in owners}) != 1:
            return None
        return owners[0]

    @property
    def is_closed(self):
        return not self.join or self.join.is_closed

    @staticmethod
    def scanned_general(bills):
        """
        scan logs based on user profile and given bills
        :param bills:
        :return:
        """
        scanned_tables = ScannedTable.objects.filter(bill__in=bills)

        user_profiles = set()
        response = []

        for scanned_table in scanned_tables:
            user_profiles.add(scanned_table.user_profile)

        for user_profile in user_profiles:
            times = [str(scanned_table.time)
                     for scanned_table in scanned_tables
                     if scanned_table.user_profile == user_profile]

            from cafepay.api_v1.serializers.PostSerializers import simple_user_profile_json_private
            response += [{
                'user_profile': simple_user_profile_json_private(user_profile),
                'times': times
            }]

        return response

    @property
    def scanned(self):
        return self.scanned_general([self, ])

    @property
    def payment_info(self):
        return get_payment_info(self.all_products)


class ProductBillRelation(models.Model):
    """
        Product - Bill M2M helper model
    """

    PENDING = '0'
    ACCEPTED = '1'
    KITCHEN = '2'
    READY = '3'
    DELIVERED = '4'
    CANCELED = '5'

    states = (
        (PENDING, _("Pending")),
        (ACCEPTED, _("Accepted")),
        (READY, _("Ready")),
        (KITCHEN, _("Kitchen")),
        (DELIVERED, _("Delivered")),
        (CANCELED, _("Canceled")),
    )

    private_id = models.UUIDField(default=uuid4, db_column="pbr_private_id")

    product = models.ForeignKey(Product, models.CASCADE)
    count = models.IntegerField(default=0)

    status = models.CharField(max_length=1, choices=states, default=PENDING)

    pickup_time = models.DateTimeField(default=timezone.now)

    # for history keeping
    original_price = models.IntegerField()
    discount = models.IntegerField()

    bill = models.ForeignKey(Bill, models.CASCADE, related_name="bill_pbrs")

    # user who added this product to the bill
    user_profile = models.ForeignKey(UserProfile,
                                     to_field='private_id',
                                     db_column='private_id',
                                     related_name="orders",
                                     on_delete=models.PROTECT,
                                     blank=True, null=True)

    is_staff = models.BooleanField(default=False)
    preferred_payment_method = models.CharField(max_length=1,
                                                choices=InvoiceConsts.methods,
                                                default=InvoiceConsts.ONLINE)

    # payment invoices/refund invoices on this PBR
    # this invoices are different than "receipt" invoices that are
    # issued when a user makes a payment
    invoices = GenericRelation(Invoice,
                               content_type_field='item_content_type',
                               object_id_field='item_id',
                               related_query_name='pbr')

    datetime = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "%d - %s : %s" % (self.pk, self.product, self.count)

    def is_status(self, status):
        return self.status == status or self.status > status

    @property
    def is_ready(self):
        return self.is_status(self.READY)

    @property
    def is_accepted(self):
        return self.is_status(self.ACCEPTED)

    @property
    def sent_to_kitchen(self):
        return self.is_status(self.KITCHEN)

    @property
    def is_delivered(self):
        return self.is_status(self.DELIVERED)

    @property
    def deposit_invoices(self):
        return self.invoices.exclude(method=InvoiceConsts.ONLINE, type=InvoiceConsts.DEPOSIT)

    @property
    def payment_invoices(self):
        this = ProductBillRelation.objects.filter(pk=self.pk)
        return get_payment_info(this, True)

    @property
    def payment_info(self):
        this = ProductBillRelation.objects.filter(pk=self.pk)
        return get_payment_info(this)

    @property
    def payed_amount(self):
        agg_payed = Invoice.objects.filter(tag=InvoiceConsts.PAYED_FOR_PRODUCT,
                                           type=InvoiceConsts.DEPOSIT,
                                           status__in=[InvoiceConsts.PAYED, InvoiceConsts.INTERNAL],
                                           pbr=self).aggregate(payed_amount=Sum('amount'))
        clean_null_values(agg_payed)

        return agg_payed['payed_amount']

    @property
    def refund_amount(self):
        agg_payed = Invoice.objects.filter(tag=InvoiceConsts.REFUND,
                                           type=InvoiceConsts.WITHDRAW,
                                           status__in=[InvoiceConsts.PAYED, InvoiceConsts.INTERNAL],
                                           pbr=self).aggregate(refund_amount=Sum('amount'))
        clean_null_values(agg_payed)

        return agg_payed['refund_amount']

    @property
    def total_amount(self):
        return self.count * self.unit_amount

    @property
    def net_payed_amount(self):
        return self.payed_amount - self.refund_amount

    @property
    def unit_amount(self) -> int:
        return self.original_price * (100 - self.discount) // 100

    @property
    def remaining_amount(self):
        return self.total_amount - self.net_payed_amount

    @property
    def net_amount(self):
        return self.total_amount - self.net_payed_amount

    @property
    def items_payed(self) -> int:
        """
        :return: Number of items that have payments
        """
        if self.unit_amount <= 0:
            return 0

        return ceil(self.net_payed_amount / self.unit_amount)


class PBRPaymentSession(models.Model):
    """
        A session of payment
        consists of  one or more pbr payments

        a user may want to make payment on multiple PBRs at the same time
        for ex. one may want pay 10$ one mocha and 5$ on pizza
        this user makes the payment with an invoice of 15$ amount
        but the individual payments are recorded in PBRPayment
        a PBRPayment with 10$ on mocha and another with 5$ on pizza
        these PBRPayments are related to each other by sharing the same
        PBRPaymentSession
    """

    user_profile = models.ForeignKey(UserProfile,
                                     related_name="pbr_payments",
                                     on_delete=models.CASCADE)

    invoice = models.OneToOneField(Invoice,
                                   related_name="pbr_session_payment",
                                   on_delete=models.CASCADE,
                                   blank=True, null=True)

    create_date = models.DateTimeField(auto_now_add=True)
    uuid = models.UUIDField(default=uuid4)

    method = models.CharField(max_length=1, choices=InvoiceConsts.methods, default=InvoiceConsts.ONLINE)
    is_manual = models.BooleanField(default=False)

    def __str__(self):
        return "%d - %s" % (self.pk, self.user_profile)

    @property
    def total_amount(self):
        return sum([pbrp.amount for pbrp in self.payments.all()])


class PBRPayment(models.Model):
    """
        Payment that made by a user profile on a pbr
    """

    session = models.ForeignKey(PBRPaymentSession, on_delete=models.CASCADE, related_name="payments")

    pbr = models.ForeignKey(ProductBillRelation, related_name="payments", on_delete=models.CASCADE)
    amount = models.PositiveIntegerField()

    @property
    def pbr_str(self):
        return self.pbr.product.name

    @property
    def owner(self):
        """Owner is available if is_manual is false"""
        return self.session.user_profile

    @property
    def payment_method(self):
        return self.session.invoice.method

    @property
    def is_manual(self):
        return self.session.is_manual


class TableJoin(models.Model):
    """
        A table join is used for holding information about tables
        and table bills. it may consist of one or more tables (through table bill)
        if no table bill is present, table join is closed
    """

    cafe = models.ForeignKey(Cafe, on_delete=models.PROTECT, related_name="joins")
    force_close = models.BooleanField(default=False)

    sent = models.BooleanField(default=False)

    last_changed_datetime = models.DateTimeField(default=timezone.now)

    datetime = models.DateTimeField(auto_now_add=True)

    ready_time = models.DateTimeField(blank=True, null=True)

    description = models.CharField(max_length=255, blank=True, null=True)

    is_self_pickup = models.BooleanField(default=False)
    include_delivery_fee = models.BooleanField(default=False)
    address = models.ForeignKey("UserProfileAddress", on_delete=models.SET_NULL, blank=True, null=True)

    # any invoice that belong to the whole table join, not a pbr
    invoices = GenericRelation(Invoice,
                               content_type_field='item_content_type',
                               object_id_field='item_id',
                               related_query_name='joins')

    def get_all_online_payed_invoices(self):
        # Manual sessions have no gateway invoice; one session can cover several items.
        return Invoice.objects.filter(
            pbr_session_payment__payments__pbr__in=self.all_products,
            method=InvoiceConsts.ONLINE, type=InvoiceConsts.DEPOSIT,
            status=InvoiceConsts.PAYED).distinct().order_by('pk')

    def refund_all_payed_invoices(self):
        # only work on PEP gateway
        from cafepay.api_v1.modules.payment.pep import pep_refund_payment
        errors = []

        for invoice in self.get_all_online_payed_invoices():
            if pep_refund_payment(invoice):
                invoice.status = InvoiceConsts.REFUNDED
                invoice.save()
                # refund the whole session
                invoice.payment_session.invoices.update(status=InvoiceConsts.REFUNDED)
            else:
                errors.append(invoice)

        return errors

    @property
    def status(self):
        _status = ProductBillRelation.DELIVERED

        for pbr in self.all_products:
            if pbr.status < _status:
                _status = pbr.status

        return _status

    @cached_property
    def is_closed(self):
        """
            if TableJoin is closed it must not be used for any action
        """

        return self.force_close or self.sent

    @cached_property
    def payment_info(self):
        return get_payment_info(self.all_products)

    @cached_property
    def all_products(self):
        return ProductBillRelation.objects.filter(bill_id__in=Bill.related_bill_ids('join_id', self.pk))

    @property
    def all_invoices(self):
        return Invoice.objects.filter(pbr__in=self.all_products, type=InvoiceConsts.DEPOSIT)

    @property
    def all_pbr_payments(self):
        return PBRPayment.objects.filter(pbr__in=self.all_products)

    @property
    def scanned(self):
        return Bill.scanned_general(self.bills.all())


class CardTransfer(models.Model):
    """A receipt submits the order optimistically; only reconciliation credits the ledger."""
    DRAFT = 'draft'
    SUBMITTED = 'submitted'
    CONFIRMED = 'confirmed'
    REJECTED = 'rejected'
    EXPIRED = 'expired'
    STATES = tuple((state, state) for state in (DRAFT, SUBMITTED, CONFIRMED, REJECTED, EXPIRED))

    uuid = models.UUIDField(default=uuid4, unique=True, editable=False)
    cafe = models.ForeignKey(Cafe, on_delete=models.PROTECT, related_name='card_transfers')
    join = models.ForeignKey(TableJoin, on_delete=models.PROTECT, related_name='card_transfers')
    customer = models.ForeignKey(UserProfile, on_delete=models.PROTECT, related_name='card_transfers')
    status = models.CharField(max_length=12, choices=STATES, default=DRAFT, db_index=True)
    amount = models.PositiveIntegerField()
    delivery_fee = models.PositiveIntegerField(default=0)
    destination_card = models.CharField(max_length=16)
    destination_holder = models.CharField(max_length=100)
    items = JSONField(default=list)
    order_fingerprint = models.CharField(max_length=64)
    receipt = models.FileField(storage=PrivateReceiptStorage(), upload_to='receipts/', blank=True)
    receipt_checksum = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(UserProfile, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='reviewed_card_transfers')
    review_note = models.CharField(max_length=500, blank=True, default='')
    payment_session = models.OneToOneField(PBRPaymentSession, on_delete=models.PROTECT,
                                           null=True, blank=True, related_name='card_transfer')

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(
            fields=['join'], condition=Q(status__in=['draft', 'submitted']),
            name='one_open_card_transfer_per_join'),
            models.UniqueConstraint(fields=['receipt_checksum'],
                condition=Q(status__in=['submitted', 'confirmed']),
                name='one_active_card_receipt_image')]


class PBRRefund(models.Model):
    """
    PBR Refund and the invoice corresponding to the refund
    """
    pbr = models.ForeignKey(ProductBillRelation, related_name="refunds", on_delete=models.PROTECT)

    # the deposit invoice that a refund is made on
    invoice = models.ForeignKey(Invoice, related_name="pbr_refund", on_delete=models.PROTECT)
    amount = models.IntegerField()


class Rating(models.Model):
    """
        Users who payed the bill can rate the bill
        with a number and a description
    """

    rate = models.DecimalField(max_digits=1, decimal_places=1)
    description = models.CharField(max_length=255, )
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, blank=False, null=False)
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, blank=False, null=False)


class Post(models.Model):
    """
        A small post with a picture
        intended for ad
    """

    EVENT = '0'
    INFO = '1'
    DISCOUNT = '2'
    OTHER = '3'

    types = ((EVENT, _("Event")),
             (INFO, _("Info")),
             (DISCOUNT, _("Discount")),
             (OTHER, _("Other")))

    image = models.ImageField(max_length=255, blank=True, null=True)
    description = models.CharField(max_length=255)
    date = models.DateTimeField(auto_now=True)

    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name="posts")
    staff = models.ForeignKey(UserProfile, related_name="posts", on_delete=models.PROTECT)
    type = models.CharField(max_length=1, choices=types, default=OTHER)

    @property
    def likes_count(self):
        return self.likes.all().count()


class Comment(models.Model):
    """
        A comment on a post
    """

    comment = models.CharField(max_length=255)
    date = models.DateTimeField(auto_now=True)

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="comments")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")


class Like(models.Model):
    """
        Like on a post
    """

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="likes")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")


class TableToken(models.Model):
    """
        Table tokens are used to allow users to add/remove orders on the table
        a table may have many table tokens, but only one active table token must exist
    """

    ACTIVE = '0'
    INACTIVE = '1'
    DELETED = '2'

    MENU_ONLY = '0'
    NORMAL = '1'
    SELF_PICKUP = '2'
    SELF_SERVICE = '3'
    PAYMENT_ONLY = '4'
    DELIVERY = '5'

    states = (
        (ACTIVE, _("Active")),
        (INACTIVE, _("Inactive")),
        (PAYMENT_ONLY, _("Payment Only")),
        (DELETED, _("Deleted"))
    )

    types = (
        (MENU_ONLY, _("Menu only")),
        (NORMAL, _("Normal")),
        (SELF_PICKUP, _("Self Pickup")),
        (SELF_SERVICE, _("Self Service")),
        (PAYMENT_ONLY, _("Payment Only")),
        (DELIVERY, _("Delivery")),
    )

    table = models.ForeignKey("Table", on_delete=models.CASCADE, related_name="table_tokens")
    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name="table_tokens")

    token = models.CharField(max_length=255, default=generate_table_token, unique=True)
    status = models.CharField(max_length=1, choices=states, default=INACTIVE)
    type = models.CharField(max_length=1, choices=types, default=NORMAL)

    has_delivery = models.BooleanField(default=False)

    @property
    def menu_only(self):
        return self.type == self.MENU_ONLY


class Table(models.Model):
    """
        Every bill is on a table object
    """

    class NoBillException(Exception):

        def __str__(self):
            return _("No bill found")

    is_delete = models.BooleanField(default=False)

    number = models.CharField(max_length=255, help_text="An arbitrary name for the table")
    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name="tables")
    staff = models.ForeignKey(UserProfile, related_name="tables", on_delete=models.PROTECT, blank=True, null=True)

    uuid = models.UUIDField(blank=True, null=True)
    table_type = models.CharField(max_length=1, choices=TableToken.types, default=TableToken.NORMAL,
                                  blank=True, null=True)

    @property
    def is_preorder(self):
        return self.table_type == TableToken.SELF_PICKUP

    def __str__(self):
        return str(self.number)

    @staticmethod
    def get_group_name(table_id, content_type):
        # todo: abstract these
        if content_type == 'table_detailed_data':
            return "table_detailed_%d" % int(table_id)
        elif content_type == 'table_simple_data':
            return "table_simple_%d" % int(table_id)

    @property
    def active_bill(self):
        """
            only active bills are used to add and remove products
            return bill if there is an active bill
            None otherwise
        """

        with transaction.atomic():
            _bill = self.bills.filter(Q(join__force_close=False) & Q(join__sent=False)).first()
            if _bill:
                return _bill
            return None

    def get_or_create_bill(self):
        """Serialize first-bill creation on the table row."""
        with transaction.atomic():
            table = Table.objects.select_for_update().get(pk=self.pk)
            bill = table.active_bill
            if bill is None:
                join = TableJoin.objects.create(cafe=table.cafe)
                bill = Bill.objects.create(table=table, join=join)
            return bill

    def add_product(self, product, user_profile, pickup_time=None, is_staff=False, quantity=1):
        with transaction.atomic():
            table = Table.objects.select_for_update().get(pk=self.pk)
            product = Product.objects.select_for_update().get(pk=product.pk)
            if product.cafe_id != table.cafe_id:
                raise APIBadRequest(_('Cafe mismatch'))
            if table.is_delete or product.is_delete or not product.available:
                raise APIBadRequest(_('Product is not available'))
            if quantity < 1 or product.count < quantity:
                raise APIBadRequest(_('Insufficient product stock'))
            bill = table.get_or_create_bill()
            bill.add_product(product, user_profile, pickup_time or timezone.now(), is_staff, quantity=quantity)
            return bill

    def remove_product(self, product, user_profile, is_staff=False, is_actor_staff=False, quantity=1):
        with transaction.atomic():
            table = Table.objects.select_for_update().get(pk=self.pk)
            product = Product.objects.select_for_update().get(pk=product.pk)
            if product.cafe_id != table.cafe_id:
                raise APIBadRequest(_('Cafe mismatch'))
            bill = table.active_bill
            if bill is None:
                raise APIBadRequest(_('No active bill'))
            if quantity < 1:
                raise APIBadRequest(_('Invalid product count'))
            bill.remove_product(product, user_profile, is_staff, is_actor_staff, quantity=quantity)
            return bill

    @property
    def active_join(self):
        """
            Every bill has a join, joins indicate what tables are joined together
            if there is an active bill, there is an active join
            returns joins if there is an active bill, None otherwise
        """

        with transaction.atomic():
            bill = self.active_bill
            if bill:
                return bill.join
            return None

    @property
    def get_or_create_join(self):
        """
            Shortcut to create an active bill and return it's join
        """

        with transaction.atomic():
            bill = self.get_or_create_bill()

            # todo: deactivate all the other in this case

            return bill.join

    def lock_receipt_order_movement(self, other=None):
        """Serialize movement with receipt checkout and preserve its order reference."""
        table_ids = [self.pk] + ([other.pk] if other else [])
        list(Table.objects.select_for_update().filter(pk__in=table_ids).order_by('pk'))
        if CardTransfer.objects.filter(
                join__bills__table_id__in=table_ids,
                join__force_close=False, join__sent=False,
                status__in=[CardTransfer.DRAFT, CardTransfer.SUBMITTED,
                            CardTransfer.CONFIRMED, CardTransfer.REJECTED]).exists():
            raise APIBadRequest('سفارش دارای پرداخت کارت‌به‌کارت قابل انتقال یا ادغام نیست.')

    def make_join(self, table):
        """
            Connect this table with the given table
            all payment info are shared

            requires:
            - cafe match
        """

        with transaction.atomic():
            self.lock_receipt_order_movement(table)
            join = self.get_or_create_join
            table_join = table.get_or_create_join
            bills = table_join.bills.all()
            bills.update(join=join)

    def transfer(self, table):
        """
            Transfer this table to the given table
            all payment info (bills) are moved to the given table
            current table will not have active bill after transfer

            requires:
            - cafe match
            - active join
        """

        with transaction.atomic():
            self.lock_receipt_order_movement(table)
            bills_to_transfer = self.active_join.bills.all()
            table_bill = table.get_or_create_bill()
            table_bill.pre_bill.add(*list(bills_to_transfer))
            bills_to_transfer.update(join=None)

    def separate(self):
        """
            Separate current table from it's join, if more than one table is present

            requires:
            - active join
            - more than one table
        """

        with transaction.atomic():
            self.lock_receipt_order_movement()
            bill = self.active_bill
            join = bill.join
            join_bill = join.bills.filter(~Q(pk=bill.pk)).first()
            join_bill.pre_bill.add(bill)
            bill.join = None
            bill.save()


class ScannedTable(models.Model):
    """
        People who scanned a table
    """
    user_profile = models.ForeignKey(UserProfile, on_delete=models.PROTECT)
    bill = models.ForeignKey(Bill, related_name='scanned_table', on_delete=models.PROTECT)
    time = models.DateTimeField(auto_now_add=True)


class CafeComment(models.Model):
    """
        Comment on a cafe
    """

    text = models.CharField(max_length=100, blank=True, null=True)
    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name="comments")
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="cafe_comments")

    verified = models.BooleanField(default=False)

    is_valid = models.BooleanField(default=True)


class RatingElement(models.Model):
    """
        a factor to be rated for a cafe
    """
    title = models.CharField(max_length=255)

    def __str__(self):
        return self.title


class RatingElementScore(models.Model):
    """
        Score for an element
    """

    el = models.ForeignKey(RatingElement, on_delete=models.CASCADE, related_name="scores")
    comment = models.ForeignKey(CafeComment, on_delete=models.CASCADE, related_name="scores")
    score = models.IntegerField(default=0, validators=[
        MinValueValidator(0),
        MaxValueValidator(5)
    ])


class DownloadFile(models.Model):
    """
    A file to download
    """

    title = models.CharField(max_length=255, blank=True, null=True)
    file = models.FileField(max_length=255)
    description = models.CharField(max_length=1024, blank=True, null=True)


class ContactUsForm(models.Model):
    full_name = models.CharField(max_length=255)
    biz_name = models.CharField(max_length=255, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=255)
    text = models.CharField(max_length=255)


class City(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return "%d - %s" % (self.pk, self.name)


class Region(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True)
    city = models.ForeignKey(City, related_name="regions", on_delete=models.CASCADE)

    lat = models.FloatField(default=0.0)
    lon = models.FloatField(default=0.0)

    def __str__(self):
        return "%d - %s | %s" % (self.pk, self.name, self.city)


class UserProfileAddress(models.Model):
    region = models.ForeignKey(Region, on_delete=models.CASCADE)
    address = models.CharField(max_length=2048)
    user_profile = models.ForeignKey(UserProfile, related_name="addresses", on_delete=models.CASCADE)

    is_clone = models.BooleanField(default=False)
    cloned_from = models.ForeignKey("UserProfileAddress", blank=True, null=True, on_delete=models.SET_NULL)

    lat = models.FloatField(default=0.0)
    lon = models.FloatField(default=0.0)

    def clone(self):

        # cannot clone a clone
        if self.is_clone:
            return self

        kwargs = {
            'region': self.region,
            'address': self.address,
            'user_profile': self.user_profile,
            'lat': self.lat,
            'lon': self.lon,
            'is_clone': True,
            'cloned_from': self
        }

        # only one identical clone
        try:
            _upa = UserProfileAddress.objects.filter(**kwargs).first()
            if not _upa:
                raise UserProfileAddress.DoesNotExist
            return _upa
        except UserProfileAddress.DoesNotExist:
            return UserProfileAddress.objects.create(**kwargs)

    def __str__(self):
        return "%d - %s (%s) | %s" % (self.pk, self.address, self.region, self.user_profile)


class CafeRegionPrice(models.Model):
    region = models.ForeignKey(Region, related_name="cafe_regions", on_delete=models.CASCADE)
    cafe = models.ForeignKey(Cafe, related_name="delivery_regions", on_delete=models.CASCADE)

    price = models.IntegerField(default=0)

    class Meta:
        unique_together = ['region', 'cafe']

    def __str__(self):
        return "%d - %d | (%s - %s)" % (self.pk, self.price, self.cafe, self.region)


class RawLog(models.Model):

    text = models.TextField()

    create_datetime = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.text


class TempToken(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid4, unique=True, blank=True)
    used = models.BooleanField(default=False, blank=True)
    host = models.CharField(max_length=255)
