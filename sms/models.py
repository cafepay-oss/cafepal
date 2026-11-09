from django.db import models
from django.utils.translation import ugettext as _
from furl import furl
from django.utils import timezone
import requests
from rest_framework.utils import json


class Message(models.Model):
    """
        A message with multiple recipients (or single recipient )
    """

    to = models.CharField(max_length=15, verbose_name=_("Recipient of the message"),
                          help_text=_("Recipient of the message"))
    message = models.CharField(max_length=500, verbose_name=_("Message Text"), help_text=_("Message Text"))

    block_code = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("Block Code"), help_text=_("Block Code"))

    last_try = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = _("Message")
        verbose_name_plural = _("Messages")


class Operator(models.Model):
    """
        The Operator that messages are sent by
    """

    FARAZ_SMS = '0'
    KAVENEGAR = '1'

    vendors = ((FARAZ_SMS, _("Faraz SMS")),
               (KAVENEGAR, _("Kavenegar")))

    name = models.CharField(max_length=255, verbose_name=_("Operator Name"), help_text=_("A name for the operator"))

    username = models.CharField(max_length=255,
                                verbose_name=_("Username"),
                                help_text=_("User name given by operator"),
                                blank=True, null=True)
    password = models.CharField(max_length=255,
                                verbose_name=_("Password"),
                                help_text=_("Password given by operator"),
                                blank=True, null=True)

    api_key = models.CharField(max_length=255,
                               verbose_name=_("API Key"),
                               help_text=_("API key given by operator"),
                               blank=True, null=True)

    template = models.CharField(max_length=255,
                                verbose_name=_("Template"),
                                help_text=_("template given by operator"),
                                blank=True, null=True)

    sender = models.CharField(max_length=15, verbose_name=_("Sender Phone Number"),
                              help_text=_("The operator phone number"),
                              blank=True, null=True)

    retry_gap_time = models.IntegerField(verbose_name=_("Retry Gap Time"),
                                         help_text=_("Time in minutes before you can try to send a message again"))

    api_endpoint = models.CharField(max_length=500, verbose_name=_("API Endpoint"), help_text=_("API Endpoint"))

    vendor = models.CharField(max_length=1, choices=vendors)

    active = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Operator")
        verbose_name_plural = _("Operators")

    def send_message(self, message):
        """
        Take a message and sends it
        :param message:
        :return:
        """

        if not self.active:
            return {'status': 'OK', 'msg': _("Message Sent")}

        if self.vendor == self.FARAZ_SMS:
            api = furl(self.api_endpoint)

            api.args['uname'] = self.username
            api.args['pass'] = self.password
            api.args['from'] = self.sender
            api.args['msg'] = message.message
            api.args['to'] = message.to

            # check for retry gap
            now = timezone.now()
            if message.last_try is None:
                message.last_try = now - timezone.timedelta(minutes=self.retry_gap_time * 2)

            if now - message.last_try >= timezone.timedelta(minutes=self.retry_gap_time):
                # eligible to retry

                message.last_try = now
                r = requests.get(api.url)

                try:
                    block_code = int(r.text)
                    message.block_code = block_code
                except:
                    err = json.loads(r.text)
                    return {'status': 'NOK', 'msg': err[1]}

                # todo: fix bug on retry gap if fails
                message.save()

                return {'status': 'OK', 'msg': _("Message Sent")}

            else:
                return {'status': 'NOK', 'msg': _("try again later")}
                # not eligible to retry
        elif self.vendor == self.KAVENEGAR:
            api = furl(self.api_endpoint.replace('{API-KEY}', self.api_key))
            api.args['receptor'] = message.to
            api.args['token'] = message.message
            api.args['template'] = self.template

            try:
                r = requests.get(api.url)
                result = json.loads(r.text)
                if result['return']['status'] == 200:
                    message.block_code = result['entries'][0]['messageid']
                    message.save()
                    return {'status': 'OK', 'msg': _("Message Sent")}
                else:
                    return {'status': 'NOK', 'msg': _("try again later")}
            except:
                return {'status': 'NOK', 'msg': _("Internal error, try again later")}
