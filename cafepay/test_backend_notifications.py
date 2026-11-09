"""Notification requests use configured authentication and bounded transport."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from cafepay.api_v1.helpers import _desktop_notification_thread


@override_settings(CAFEPAY_LOCAL_RECOVERY=False, PUSH_SERVICE_URL='https://push.example.test/api/vapid-data',
                   PUSH_SERVICE_TOKEN='test-service-token')
class PushTransportTests(SimpleTestCase):
    def table(self):
        endpoints = Mock()
        endpoints.all.return_value = [SimpleNamespace(keys='private-test-key', text='subscription-test')]
        return SimpleNamespace(is_preorder=True, cafe=SimpleNamespace(push_endpoints=endpoints))

    @patch('cafepay.api_v1.helpers.requests.post')
    def test_push_uses_service_auth_timeout_and_tls(self, post):
        self.assertTrue(_desktop_notification_thread(self.table()))
        kwargs = post.call_args[1]
        self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer test-service-token'})
        self.assertEqual(kwargs['timeout'], (3.05, 5))
        self.assertIs(kwargs['verify'], True)
        post.return_value.raise_for_status.assert_called_once_with()

    @patch('cafepay.api_v1.helpers.requests.post', side_effect=requests.Timeout('private-test-key'))
    def test_network_failure_does_not_leak_keys_or_break_order(self, post):
        with self.assertLogs('cafepay.api_v1.helpers', level='WARNING') as logs:
            self.assertFalse(_desktop_notification_thread(self.table()))
        self.assertNotIn('private-test-key', str(logs.output))
        self.assertNotIn('test-service-token', str(logs.output))

    @override_settings(PUSH_SERVICE_TOKEN='')
    @patch('cafepay.api_v1.helpers.requests.post')
    def test_unconfigured_push_does_not_send(self, post):
        self.assertFalse(_desktop_notification_thread(self.table()))
        post.assert_not_called()
