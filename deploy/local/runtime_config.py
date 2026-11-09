"""Environment configuration for the isolated local recovery stack."""
import os

SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = os.environ.get('DJANGO_DEBUG', 'false').lower() == 'true'
DEMO = True
KAVENEGAR_API_KEY = ''
VANDAR_API_KEY = ''
PEP_TERMINAL_CODE = ''
PEP_MERCHANT_CODE = ''
PEP_PRIVATE_KEY = ''

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'HOST': 'db',
    'PORT': '5432',
    'NAME': os.environ['POSTGRES_DB'],
    'USER': os.environ['POSTGRES_USER'],
    'PASSWORD': os.environ['POSTGRES_PASSWORD'],
}}
CHANNEL_LAYERS = {'default': {
    'BACKEND': 'channels_redis.core.RedisChannelLayer',
    'CONFIG': {'hosts': [('redis', 6379)]},
}}
