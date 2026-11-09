"""Run after startup to verify actual HTTP responses from the local stack."""
import json
import urllib.request

for name, url in [('API', 'http://localhost:8000/healthz/'),
                  ('Django admin', 'http://localhost:8000/admin/login/'),
                  ('Customer app', 'http://localhost:3000/'),
                  ('Payment receipt route', 'http://localhost:3000/paymentResult?status=200'),
                  ('Admin app', 'http://localhost:3001/')]:
    with urllib.request.urlopen(url, timeout=15) as response:
        body = response.read()
        assert response.status == 200, (name, response.status)
        if name == 'API':
            assert json.loads(body)['status'] == 'ok'
        else:
            assert b'<html' in body.lower(), name + ' did not return HTML'
    print(name + ': HTTP check passed')
print('These HTTP checks do not test browser workflows.')
