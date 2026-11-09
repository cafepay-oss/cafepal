import json

from django.http import HttpResponse
from django.utils import timezone

from cafepay.api_v1.helpers import datetime_to_asia_tehran


def host_view(request):
    local = datetime_to_asia_tehran(timezone.now())
    utc = timezone.now()

    response = {
        'local': str(local.date()),
        'utc': str(utc.date())
    }
    return HttpResponse(json.dumps(response))
