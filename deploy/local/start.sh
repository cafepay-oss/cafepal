#!/bin/sh
set -eu
python manage.py check
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec daphne -b 0.0.0.0 -p 8000 cafepal.asgi:application
