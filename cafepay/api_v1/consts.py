from django.utils.translation import gettext as _


class InvoiceConsts:
    # balance types
    DEPOSIT = '0'
    WITHDRAW = '1'
    CLEARING = '2'

    # states
    PAYED = '0'
    CREATED = '1'
    IN_PAYMENT = '2'
    REJECTED = '3'
    INTERNAL = '4'
    REFUNDED = '5'

    # tags
    CHARGE_WALLET = '3'
    CHARGE_WALLET_FROM_CAFEPAY = '6'
    REFUND = '0'
    PAYED_FOR_PRODUCT = '1'
    PAY_PBR_SESSION = '2'
    CLEARING_TAG = '5'
    DELIVERY_FEE = '6'

    # methods
    ONLINE = '0'
    POS = '1'
    CASH = '2'
    CARD_TO_CARD = '3'
    DISCOUNT = '4'
    GUEST = '5'

    tags = ((REFUND, _("Refund")),
            (CHARGE_WALLET, _("Charge Wallet")),
            (CHARGE_WALLET_FROM_CAFEPAY, _("Charge Wallet From Cafepay")),
            (PAYED_FOR_PRODUCT, _("Payed for product")),
            (PAY_PBR_SESSION, _("Pay for session")),
            (DELIVERY_FEE, _("Delivery Fee")),
            (CLEARING_TAG, _("Clearing")))

    balance_types = (
        (DEPOSIT, _('Deposit')),
        (WITHDRAW, _('Withdraw')),
        (CLEARING, _("Clearing"))
    )

    states = (
        (PAYED, _('Payed')),
        (CREATED, _('Created')),
        (IN_PAYMENT, _('In Payment')),
        (REJECTED, _('Rejected')),
        (REFUNDED, _('Refunded')),
        (INTERNAL, _("Internal"))
    )

    methods = (
        (ONLINE, _("Online")),
        (POS, _("POS")),
        (CASH, _("CASH")),
        (DISCOUNT, _("Discount")),
        (CARD_TO_CARD, _("CardToCard")),
        (GUEST, _("Guest"))
    )


class AccountInfoConsts:
    VERIFIED = '0'
    PENDING = '1'
    REJECTED = '2'

    _account_verification_states = ((VERIFIED, _('Verified')),
                                    (PENDING, _('Pending')),
                                    (REJECTED, _('Rejected')))


class CharacterFieldConsts:
    EMAIL = '0'
    PHONE = '1'
    CATEGORY = '2'
    GROUP = '3'

    types = (
        (EMAIL, "Email"),
        (PHONE, "Phone"),
        (GROUP, "Group"),
        (CATEGORY, "Category")
    )


class UserProfileConsts:
    PENDING = '0'
    VERIFIED = '1'

    states = (
        (PENDING, "Pending"),
        (VERIFIED, "Verified"),
    )


class CafeUserProfileRelationConsts:
    PENDING = '0'
    VERIFIED = '1'
    REMOVED = '2'

    states = (
        (PENDING, _("Pending")),
        (VERIFIED, _("Verified")),
        (REMOVED, _("Removed"))
    )


class DateTimeRangeConsts:
    SATURDAY = '0'
    SUNDAY = '1'
    MONDAY = '2'
    TUESDAY = '3'
    WEDNESDAY = '4'
    THURSDAY = '5'
    FRIDAY = '6'

    days = (
        (SATURDAY, "Saturday"),
        (SUNDAY, "Sunday"),
        (MONDAY, "Monday"),
        (TUESDAY, "Tuesday"),
        (WEDNESDAY, "Wednesday"),
        (THURSDAY, "Thursday"),
        (FRIDAY, "Friday")
    )
