"""Create a separate cafe for local browser checkout checks."""
import json
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cafepay.api_v1.consts import CharacterFieldConsts, UserProfileConsts
from cafepay.models import Cafe, CharacterField, Menu, Table, TableToken, UserProfile, Wallet


DEMO_USERNAME = 'cafepay-local-demo'
DEMO_DESCRIPTION = 'Local browser test cafe. Created by seed_local_demo.'
CUSTOMER_USERNAME = 'cafepay-local-customer'
CUSTOMER_EMAIL = 'customer@cafepay.local.invalid'
CUSTOMER_PHONE = '09000000002'


class Command(BaseCommand):
    help = 'Create a local test cafe and customer. Preserve restored cafes and products.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False):
            raise CommandError('This command requires CAFEPAY_LOCAL_RECOVERY=true.')
        cafe = Cafe.objects.filter(username=DEMO_USERNAME).first()
        if cafe and cafe.description != DEMO_DESCRIPTION:
            raise CommandError('The demo cafe username already exists. Existing data remains unchanged.')

        customer = User.objects.filter(username=CUSTOMER_USERNAME).first()
        if customer and customer.email != CUSTOMER_EMAIL:
            raise CommandError('The demo customer username already exists. Existing data remains unchanged.')
        profile = UserProfile.objects.filter(phone_number=CUSTOMER_PHONE).first()
        if profile and (not customer or profile.django_user_id != customer.pk):
            raise CommandError('The demo customer phone already exists. Existing data remains unchanged.')
        if not customer:
            customer = User.objects.create_user(CUSTOMER_USERNAME, CUSTOMER_EMAIL, 'customer')
        if not profile:
            if UserProfile.objects.filter(django_user=customer).exists():
                raise CommandError('The demo customer has another phone. Existing data remains unchanged.')
            profile = UserProfile.objects.create(
                django_user=customer, phone_number=CUSTOMER_PHONE,
                first_name='Local', last_name='Customer', wallet=Wallet.objects.create(),
                verification_status=UserProfileConsts.VERIFIED)

        call_command('bootstrap_local_admin', stdout=self.stdout)
        staff = User.objects.get(username='admin').user_profile
        if not cafe:
            cafe = Cafe.objects.create(
                username=DEMO_USERNAME, name='CafePay Local Demo', address='Local browser test',
                description=DEMO_DESCRIPTION, wallet=Wallet.objects.create(), is_active=True,
                menu_prices_on=True, menu_items_on=True, cafepay_fee=0)
        menu, _ = Menu.objects.get_or_create(cafe=cafe, name='Local menu',
                                             defaults={'staff': staff, 'is_active': True})
        category, _ = CharacterField.objects.get_or_create(
            cafe=cafe, menu=menu, title='Coffee', type=CharacterFieldConsts.CATEGORY,
            defaults={'staff': staff})
        table, _ = Table.objects.get_or_create(cafe=cafe, number='Local table',
                                               defaults={'staff': staff, 'uuid': uuid4()})
        token, _ = TableToken.objects.get_or_create(cafe=cafe, table=table,
                                                     defaults={'status': TableToken.ACTIVE})
        self.stdout.write(json.dumps({
            'cafe_id': cafe.pk, 'cafe_username': cafe.username, 'menu_id': menu.pk,
            'category_id': category.pk, 'table_id': table.pk, 'table_token': token.token,
            'customer_username': CUSTOMER_USERNAME, 'customer_phone': CUSTOMER_PHONE,
        }, sort_keys=True))
