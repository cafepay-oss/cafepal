"""Local administrator and cafe registration regression tests."""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from cafepay.models import Cafe, CafeUserProfileRelation, Product, TableToken, UserProfile, Wallet
from cafepay.management.commands.seed_local_demo import DEMO_USERNAME


@override_settings(CAFEPAY_LOCAL_RECOVERY=True)
class LocalAccountTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def bootstrap(self):
        call_command('bootstrap_local_admin', stdout=StringIO())
        return User.objects.get(username='admin')

    def login(self, password='admin'):
        return self.client.post('/api/v1/local/login/',
                                {'username': 'admin', 'password': password}, format='json')

    def test_bootstrap_creates_complete_account_and_preserves_password_on_rerun(self):
        user = self.bootstrap()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password('admin'))
        self.assertEqual(user.user_profile.wallet.balance, 0)
        self.assertTrue(user.user_profile.is_elevated_user)
        wallet_id = user.user_profile.wallet_id
        user.set_password('changed-local-password')
        user.save()
        self.bootstrap()
        user.refresh_from_db()
        self.assertTrue(user.check_password('changed-local-password'))
        self.assertEqual(user.user_profile.wallet_id, wallet_id)
        self.assertEqual(Wallet.objects.count(), 1)

    def test_bootstrap_refuses_restored_admin_and_preserves_credentials(self):
        user = User.objects.create_user('admin', password='restored-password')
        password_hash = user.password
        with self.assertRaisesMessage(CommandError, 'Restored credentials remain unchanged'):
            self.bootstrap()
        user.refresh_from_db()
        self.assertEqual(user.password, password_hash)
        self.assertFalse(user.is_superuser)
        self.assertFalse(UserProfile.objects.exists())
        self.assertFalse(Wallet.objects.exists())

    def test_bootstrap_uses_unused_phone_number(self):
        existing = User.objects.create_user('existing', password='restored-password')
        profile = UserProfile.objects.create(django_user=existing, phone_number='09000000000',
                                              wallet=Wallet.objects.create())
        user = self.bootstrap()
        self.assertNotEqual(user.user_profile.phone_number, profile.phone_number)
        profile.refresh_from_db()
        self.assertEqual(profile.django_user, existing)

    def test_login_lists_all_cafes_without_changing_staff_records(self):
        self.bootstrap()
        cafes = [Cafe.objects.create(name='Cafe %s' % index, address='Local test',
                                     wallet=Wallet.objects.create()) for index in range(2)]
        response = self.login()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({item['cafe']['pk'] for item in response.data['cafe_relations']},
                         {cafe.pk for cafe in cafes})
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + response.data['token'])
        refreshed = self.client.get('/api/v1/auth/info/')
        self.assertEqual(refreshed.status_code, 200, refreshed.data)
        self.assertEqual(refreshed.data, response.data)
        self.assertFalse(CafeUserProfileRelation.objects.exists())

    def test_login_rejects_invalid_credentials_and_inactive_accounts(self):
        user = self.bootstrap()
        self.assertEqual(self.login('wrong-password').status_code, 400)
        user.is_active = False
        user.save()
        self.assertEqual(self.login().status_code, 400)
        self.assertFalse(Token.objects.exists())

    def test_local_mode_is_required_for_bootstrap_login_and_all_cafe_access(self):
        self.bootstrap()
        Cafe.objects.create(name='Private cafe', address='Local test', wallet=Wallet.objects.create())
        token = self.login().data['token']
        with self.settings(CAFEPAY_LOCAL_RECOVERY=False):
            with self.assertRaises(CommandError):
                self.bootstrap()
            self.assertEqual(self.login().status_code, 404)
            self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
            self.assertEqual(self.client.get('/api/v1/auth/info/').data['cafe_relations'], [])

    def test_regular_user_does_not_receive_all_cafe_access(self):
        user = User.objects.create_user('customer', password='local-password')
        UserProfile.objects.create(django_user=user, phone_number='09000000005',
                                   wallet=Wallet.objects.create())
        Cafe.objects.create(name='Unrelated cafe', address='Local test', wallet=Wallet.objects.create())
        response = self.client.post('/api/v1/local/login/',
                                    {'username': 'customer', 'password': 'local-password'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['cafe_relations'], [])

    def test_admin_registers_cafe_and_creates_product(self):
        self.bootstrap()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.login().data['token'])
        response = self.client.post('/api/v1/cafe/add/', {
            'name': 'New local cafe', 'address': 'Local registration test',
            'description': 'Cafe created through the API',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        cafe = Cafe.objects.get(pk=response.data['pk'])
        self.assertEqual(cafe.wallet.balance, 0)
        self.assertTrue(cafe.staff_roles.filter(code_name='creator').exists())
        self.assertEqual(self.client.get('/api/v1/auth/info/').data['cafe_relations'][0]['cafe']['pk'], cafe.pk)
        category = self.client.post('/api/v1/cafe/%s/category/add/' % cafe.pk,
                                     {'title': 'Coffee'}, format='json')
        self.assertEqual(category.status_code, 201, category.data)
        product = self.client.post('/api/v1/cafe/%s/product/add/' % cafe.pk, {
            'name': 'Registration espresso', 'original_price': 25000, 'count': 10, 'available': True,
            'category': category.data['pk'],
        }, format='json')
        self.assertEqual(product.status_code, 201, product.data)
        self.assertEqual(product.data['name'], 'Registration espresso')

    def test_demo_seed_is_repeatable_and_does_not_create_products(self):
        call_command('seed_local_demo', stdout=StringIO())
        cafe = Cafe.objects.get(username=DEMO_USERNAME)
        wallet_count = Wallet.objects.count()
        call_command('seed_local_demo', stdout=StringIO())
        self.assertEqual(Cafe.objects.count(), 1)
        self.assertEqual(Wallet.objects.count(), wallet_count)
        self.assertTrue(cafe.is_active)
        self.assertTrue(cafe.menu_items_on)
        self.assertTrue(TableToken.objects.filter(cafe=cafe, status=TableToken.ACTIVE).exists())
        self.assertFalse(Product.objects.exists())
        self.assertTrue(UserProfile.objects.filter(phone_number='09000000002').exists())

    def test_demo_seed_refuses_existing_cafe_and_customer_phone(self):
        cafe = Cafe.objects.create(username=DEMO_USERNAME, name='Restored cafe',
                                   address='Restored address', wallet=Wallet.objects.create())
        with self.assertRaises(CommandError):
            call_command('seed_local_demo', stdout=StringIO())
        self.assertFalse(User.objects.exists())
        cafe.delete()
        existing = User.objects.create_user('existing-customer')
        UserProfile.objects.create(django_user=existing, phone_number='09000000002',
                                   wallet=Wallet.objects.create())
        with self.assertRaises(CommandError):
            call_command('seed_local_demo', stdout=StringIO())
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(Cafe.objects.exists())

    def test_demo_seed_requires_local_mode(self):
        with self.settings(CAFEPAY_LOCAL_RECOVERY=False):
            with self.assertRaises(CommandError):
                call_command('seed_local_demo', stdout=StringIO())
        self.assertFalse(User.objects.exists())
        self.assertFalse(Cafe.objects.exists())
