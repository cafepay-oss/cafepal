"""Shared fixtures for isolated backend regression tests."""
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from cafepay.api_v1.consts import CafeUserProfileRelationConsts, CharacterFieldConsts
from cafepay.models import (Bill, Cafe, CafeUserProfileRelation, CafeUserProfileRelationRole,
                           CharacterField, Product, ProductBillRelation, Table, TableJoin,
                           TableToken, UserProfile, Wallet)


class BackendFixtures:
    def setUp(self):
        super().setUp()
        for module in ('TableViews', 'JoinViews', 'PBRPaymentViews'):
            notifier = patch('cafepay.api_v1.views.%s.notify_watchers' % module)
            notifier.start()
            self.addCleanup(notifier.stop)
        self.client = APIClient()
        self.customer = self.make_user('customer', '09000000002')
        self.outsider = self.make_user('outsider', '09000000003')
        self.staff = self.make_user('staff', '09000000004')
        self.other_staff = self.make_user('other-staff', '09000000005')
        self.cafe = self.make_cafe('Test cafe', self.staff)
        self.other_cafe = self.make_cafe('Other cafe', self.other_staff)
        self.table = Table.objects.create(cafe=self.cafe, number='1', uuid=uuid4())
        self.table_token = TableToken.objects.create(
            cafe=self.cafe, table=self.table, status=TableToken.ACTIVE)
        self.product = self.make_product(self.cafe, self.staff)
        self.join = TableJoin.objects.create(cafe=self.cafe)
        self.bill = Bill.objects.create(table=self.table, join=self.join)
        self.pbr = ProductBillRelation.objects.create(
            bill=self.bill, product=self.product, user_profile=self.customer,
            count=2, original_price=10000, discount=0)

    def make_user(self, name, phone):
        user = User.objects.create_user(username=name)
        return UserProfile.objects.create(django_user=user, phone_number=phone,
                                          wallet=Wallet.objects.create())

    def make_cafe(self, name, staff):
        cafe = Cafe.objects.create(name=name, address='Isolated test',
                                   wallet=Wallet.objects.create(), is_active=True,
                                   menu_prices_on=True, menu_items_on=True)
        role = CafeUserProfileRelationRole.objects.create(
            cafe=cafe, code_name='staff', display_name='Staff')
        CafeUserProfileRelation.objects.create(
            role=role, user_profile=staff, status=CafeUserProfileRelationConsts.VERIFIED)
        return cafe

    def make_product(self, cafe, staff):
        category = CharacterField.objects.create(
            title='Coffee', type=CharacterFieldConsts.CATEGORY, cafe=cafe, staff=staff)
        return Product.objects.create(cafe=cafe, staff=staff, category=category,
                                       name='Espresso', count=10, original_price=10000)

    def authenticate(self, profile):
        self.client.force_authenticate(user=profile.django_user if profile else None)
