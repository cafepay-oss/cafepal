import json

from django.conf.urls import url
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.models import Permission
from django.urls import reverse, path
from django.utils.html import format_html

from .api_v1.serializers.WalletAndInvoiceSerializers import InvoiceSerializer
from .models import *


# Register your models here.


class WalletAdmin(admin.ModelAdmin):
    list_display = ['owner', 'phone_number', 'balance']

    @staticmethod
    def owner(instance):
        return instance.owner_string

    @staticmethod
    def phone_number(instance):
        return UserProfile.objects.get(wallet=instance).phone_number


class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['owner', 'amount', 'type', 'status', 'create_datetime',
                    'tag', 'uuid', 'method', 'item']
    search_fields = ['uuid', ]
    list_filter = ['type', 'tag', 'status', 'method']

    @staticmethod
    def owner(instance):
        return instance.wallet.owner_string


class TableAdmin(admin.ModelAdmin):
    list_display = ['number', 'active_bill', 'active_join', 'uuid']
    search_fields = ['uuid', 'number']


class TableJoinAdmin(admin.ModelAdmin):
    list_display = ['pk', 'is_closed', 'force_close', 'sent', 'datetime']


class BillAdmin(admin.ModelAdmin):
    list_display = ['pk', 'table', 'payment_info', ]


class CafeUserProfileRelationRoleAdmin(admin.ModelAdmin):
    list_display = ['pk', 'cafe_id', 'cafe__name', 'display_name', 'code_name']

    @staticmethod
    def cafe_id(instance):
        return str(instance.cafe.pk)

    @staticmethod
    def cafe__name(instance):
        return instance.cafe.name


class CafeUserProfileRelationAdmin(admin.ModelAdmin):
    list_display = ['pk', 'cafe_id', 'cafe__name', 'user_profile__phone_number', 'user_profile__name',
                    'role__display_name', 'role_id', 'status']

    @staticmethod
    def cafe_id(instance):
        return str(instance.role.cafe.pk)

    @staticmethod
    def cafe__name(instance):
        return instance.role.cafe.name

    @staticmethod
    def user_profile__name(instance):
        return str(instance.user_profile.pk) + \
               " - " + \
               str(instance.user_profile.full_name)

    @staticmethod
    def user_profile__phone_number(instance):
        return instance.user_profile.phone_number

    @staticmethod
    def role__display_name(instance):
        return instance.role.display_name

    @staticmethod
    def role_id(instance):
        return str(instance.role.pk)


class ProductRatingCommentAdmin(admin.ModelAdmin):
    list_display = ['pk', 'commenter', 'comment', 'rate', 'status', 'is_valid', 'product']
    list_editable = ['status', ]


admin.site.register(ProductRatingComment, ProductRatingCommentAdmin)


class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'cafe', 'order']
    list_editable = ['order', ]


admin.site.register(AccountInfo)
admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Wallet, WalletAdmin)


class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone_number', 'private_id']
    list_editable = ['private_id']


class CafeAdmin(admin.ModelAdmin):
    list_display = ['name', 'wallet', 'total_deposits_amount',
                    'total_online_deposits_amount',
                    'to_be_cleared', 'to_be_cleared_net',
                    'cafepay_fee',
                    'fee_payer', 'clear']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:cafe_id>/deposit/',
                 self.admin_site.admin_view(self._clear_to_be_cleared),
                 name='account-clear',
                 ),
        ]
        return custom_urls + urls

    def _clear_to_be_cleared(self, request, cafe_id, *args, **kwargs):
        cafe = get_object_or_404(Cafe, pk=cafe_id)

        amount = int(cafe._to_be_cleared)

        if amount == 0:
            return HttpResponse("All Clear")

        wallet = cafe.wallet

        _invoice = Invoice.objects.create(
            wallet=wallet,
            amount=amount,
            cafepay_fee=cafe.cafepay_fee,
            fee_payer=cafe.fee_payer,
            type=InvoiceConsts.CLEARING,
            status=InvoiceConsts.PAYED,
            tag=InvoiceConsts.CLEARING_TAG,
            method=InvoiceConsts.ONLINE,
        )

        _invoice_data = InvoiceSerializer(instance=_invoice).data

        return HttpResponse(json.dumps(_invoice_data))

    @staticmethod
    def clear(obj):
        return format_html(
            '<a class="button" href="{}">Clear</a>&nbsp;',
            reverse('admin:account-clear', kwargs={'cafe_id': obj.pk})
        )


admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(Cafe, CafeAdmin)
admin.site.register(CharacterField)
admin.site.register(DateTimeRange)
admin.site.register(Permission)
admin.site.register(Post)
admin.site.register(Bill)
admin.site.register(ScannedTable)
admin.site.register(Gallery)
admin.site.register(PrinterType)
admin.site.register(Printer)
admin.site.register(PrinterJob)
admin.site.register(Comment)
admin.site.register(Product, ProductAdmin)
admin.site.register(ProductImage)
admin.site.register(Menu)
admin.site.register(CafeUserProfileRelationRole, CafeUserProfileRelationRoleAdmin)
admin.site.register(CafeUserProfileRelation, CafeUserProfileRelationAdmin)
admin.site.register(Table, TableAdmin)


# admin.site.register(Bill, BillAdmin)
# admin.site.register(TableJoin, TableJoinAdmin)


class UPPVAdmin(admin.ModelAdmin):
    list_display = ['pk', 'user_profile__phone_number', 'code', 'used', 'burnt']

    list_filter = ['used', 'user_profile__phone_number']

    @staticmethod
    def user_profile__phone_number(instance):
        return instance.user_profile.phone_number


admin.site.register(UserProfilePhoneVerification, UPPVAdmin)


class TableTokenAdmin(admin.ModelAdmin):
    list_display = ['pk', 'token', 'status', 'type']
    list_editable = ['token', 'status', 'type']
    search_fields = ['token', ]
    list_filter = ['status', 'type', 'cafe', ]


admin.site.register(TableToken, TableTokenAdmin)


class ProductBillRelationAdmin(admin.ModelAdmin):
    list_display = ['pk', 'payed_amount', 'product', 'unit_amount', 'total_amount', 'refund_amount', 'datetime']


class CafeCommentAdmin(admin.ModelAdmin):
    list_display = ['pk', 'verified', 'is_valid', 'text']

    list_editable = ['verified']


class PBRPaymentsAdmin(admin.ModelAdmin):
    list_display = ['pk', 'session', 'pbr', 'amount']


class PBRPaymentSessionAdmin(admin.ModelAdmin):
    list_display = ['pk', 'user_profile', 'invoice', 'method', 'is_manual', 'amount']

    @staticmethod
    def amount(instance):
        if instance.invoice:
            return instance.invoice.amount
        return "N/A"


admin.site.register(ProductBillRelation, ProductBillRelationAdmin)
admin.site.register(PBRPaymentSession, PBRPaymentSessionAdmin)
admin.site.register(PBRPayment, PBRPaymentsAdmin)
admin.site.register(RatingElement)
admin.site.register(CafeComment, CafeCommentAdmin)

# class TableJoinAdmin(admin.ModelAdmin):
#
#     list_display = ['cafe', 'force_close', 'sent', 'is_closed']

admin.site.register(TableJoin, TableJoinAdmin)


class ContactUsFormAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone_number', 'text']


class PushEndpointAdmin(admin.ModelAdmin):
    list_display = ['pk', 'text', 'keys', 'cafe']


admin.site.register(PushEndpoint, PushEndpointAdmin)
admin.site.register(ContactUsForm, ContactUsFormAdmin)


class CafeWalletAdmin(admin.ModelAdmin):
    list_display = ['pk', 'user_profile', 'cafe', 'wallet__balance']

    def wallet__balance(self, instance):
        return instance.wallet.balance


admin.site.register(CafeWallet, CafeWalletAdmin)


class CityAdmin(admin.ModelAdmin):
    list_display = ['pk', 'name', ]


class RegionAdmin(admin.ModelAdmin):
    list_display = ['pk', 'name', 'city']


class CafeRegionPriceAdmin(admin.ModelAdmin):
    list_display = ['pk', 'cafe', 'price', 'region']


class RawLogAdmin(admin.ModelAdmin):
    list_display = ['pk', 'create_datetime']


admin.site.register(City, CityAdmin)
admin.site.register(Region, RegionAdmin)
admin.site.register(CafeRegionPrice, CafeRegionPriceAdmin)
admin.site.register(TempToken)
admin.site.register(RawLog, RawLogAdmin)
