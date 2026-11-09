import uuid
from django.contrib.postgres.fields import JSONField
from django.db import migrations, models
import django.db.models.deletion
from cafepay.receipt_storage import PrivateReceiptStorage


class Migration(migrations.Migration):
    dependencies = [('cafepay', '0215_rawlog_create_datetime')]

    operations = [
        migrations.AddField('cafe', 'card_transfer_enabled', models.BooleanField(default=False)),
        migrations.AddField('cafe', 'card_transfer_number', models.CharField(max_length=16, blank=True, default='')),
        migrations.AddField('cafe', 'card_transfer_holder', models.CharField(max_length=100, blank=True, default='')),
        migrations.CreateModel(name='CardTransfer', fields=[
            ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('uuid', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
            ('status', models.CharField(max_length=12, default='draft', db_index=True,
                choices=[(s, s) for s in ('draft', 'submitted', 'confirmed', 'rejected', 'expired')])),
            ('amount', models.PositiveIntegerField()),
            ('delivery_fee', models.PositiveIntegerField(default=0)),
            ('destination_card', models.CharField(max_length=16)),
            ('destination_holder', models.CharField(max_length=100)),
            ('items', JSONField(default=list)),
            ('order_fingerprint', models.CharField(max_length=64)),
            ('receipt', models.FileField(storage=PrivateReceiptStorage(), upload_to='receipts/', blank=True)),
            ('receipt_checksum', models.CharField(max_length=64, null=True, blank=True, db_index=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('submitted_at', models.DateTimeField(null=True, blank=True)),
            ('reviewed_at', models.DateTimeField(null=True, blank=True)),
            ('review_note', models.CharField(max_length=500, blank=True, default='')),
            ('cafe', models.ForeignKey(to='cafepay.Cafe', on_delete=django.db.models.deletion.PROTECT, related_name='card_transfers')),
            ('join', models.ForeignKey(to='cafepay.TableJoin', on_delete=django.db.models.deletion.PROTECT, related_name='card_transfers')),
            ('customer', models.ForeignKey(to='cafepay.UserProfile', on_delete=django.db.models.deletion.PROTECT, related_name='card_transfers')),
            ('reviewed_by', models.ForeignKey(to='cafepay.UserProfile', on_delete=django.db.models.deletion.PROTECT, related_name='reviewed_card_transfers', null=True, blank=True)),
            ('payment_session', models.OneToOneField(to='cafepay.PBRPaymentSession', on_delete=django.db.models.deletion.PROTECT, related_name='card_transfer', null=True, blank=True)),
        ], options={'ordering': ['-created_at', '-pk']}),
        migrations.AddConstraint('cardtransfer', models.UniqueConstraint(
            fields=['join'], condition=models.Q(status__in=['draft', 'submitted']),
            name='one_open_card_transfer_per_join')),
        migrations.AddConstraint('cardtransfer', models.UniqueConstraint(
            fields=['receipt_checksum'], condition=models.Q(status__in=['submitted', 'confirmed']),
            name='one_active_card_receipt_image')),
    ]
