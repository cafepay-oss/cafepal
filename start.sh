#!/bin/bash
echo yes | python manage.py collectstatic
python manage.py migrate
daphne -b 0.0.0.0 -p 8000 cafepal.asgi:application