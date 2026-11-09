"""Copy to secret.py and set these environment variables before starting Django."""
import os

SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = os.environ.get('DJANGO_DEBUG', 'false').lower() == 'true'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ.get('POSTGRES_DB', 'cafepay'),
    'USER': os.environ.get('POSTGRES_USER', 'cafepay'),
    'PASSWORD': os.environ['POSTGRES_PASSWORD'],
    'HOST': os.environ.get('POSTGRES_HOST', 'db'),
    'PORT': os.environ.get('POSTGRES_PORT', '5432'),
}}
CHANNEL_LAYERS = {'default': {
    'BACKEND': 'channels_redis.core.RedisChannelLayer',
    'CONFIG': {'hosts': [(os.environ.get('REDIS_HOST', 'redis'),
                          int(os.environ.get('REDIS_PORT', '6379')))]},
}}
KAVENEGAR_API_KEY = os.environ.get('KAVENEGAR_API_KEY', '')
VANDAR_API_KEY = os.environ.get('VANDAR_API_KEY', '')
PEP_TERMINAL_CODE = os.environ.get('PEP_TERMINAL_CODE', '')
PEP_MERCHANT_CODE = os.environ.get('PEP_MERCHANT_CODE', '')
PEP_PRIVATE_KEY = os.environ.get('PEP_PRIVATE_KEY', '')
DEMO = os.environ.get('CAFEPAY_DEMO', 'true').lower() == 'true'
