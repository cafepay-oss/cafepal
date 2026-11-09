"""Create the administrator for the isolated local recovery stack."""
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cafepay.api_v1.consts import UserProfileConsts
from cafepay.models import UserProfile, Wallet


LOCAL_ADMIN_GROUP = 'cafepay-local-administrator'
LOCAL_ADMIN_EMAIL = 'admin@cafepay.local.invalid'


class Command(BaseCommand):
    help = 'Create the local admin/admin account without changing restored accounts.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, 'CAFEPAY_LOCAL_RECOVERY', False):
            raise CommandError('This command requires CAFEPAY_LOCAL_RECOVERY=true.')

        user = User.objects.filter(username='admin').first()
        if user:
            local_account = (user.email == LOCAL_ADMIN_EMAIL and
                             user.groups.filter(name=LOCAL_ADMIN_GROUP).exists())
            if not local_account:
                raise CommandError('The admin account already exists. Restored credentials remain unchanged.')
            self.stdout.write('The local administrator already exists. Its password remains unchanged.')
            return

        # Select an unused synthetic phone number. Preserve all restored profiles.
        phone = next(('0900000%04d' % number for number in range(10000)
                      if not UserProfile.objects.filter(phone_number='0900000%04d' % number).exists()), None)
        if phone is None:
            raise CommandError('No synthetic phone number is available for the local administrator.')

        user = User.objects.create_superuser('admin', LOCAL_ADMIN_EMAIL, 'admin')
        group, _ = Group.objects.get_or_create(name=LOCAL_ADMIN_GROUP)
        user.groups.add(group)
        UserProfile.objects.create(
            django_user=user, phone_number=phone, first_name='Local', last_name='Administrator',
            wallet=Wallet.objects.create(), is_elevated_user=True,
            verification_status=UserProfileConsts.VERIFIED)
        self.stdout.write(self.style.SUCCESS('Created the local administrator: admin / admin.'))
