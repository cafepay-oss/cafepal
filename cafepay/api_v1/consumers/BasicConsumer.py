import json
from json import JSONDecodeError
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils.translation import gettext as _
from rest_framework.authtoken.models import Token
from channels.db import database_sync_to_async

from cafepay.api_v1.consumers.ConsumerView import ConsumerResponse
from cafepay.api_v1.consumers.helpers import SocketException
from rest_framework.renderers import JSONRenderer


def dict_to_json(dict_data):
    try:
        return JSONRenderer().render(dict_data).decode("utf-8")
    except:
        print("-------------")
        print(dict_data)
        print("-------------")


class BasicConsumer(AsyncWebsocketConsumer):

    async def authenticate(self, authorization_header):
        token = authorization_header.replace("Token ", "")

        try:
            token_obj = await self.db_get(Token, key=token)
            return token_obj.user

        except Token.DoesNotExist:
            await self.channel_400(_("Invalid Token"))

            raise SocketException(_("Invalid Token"))

    async def send_back_info(self, dict_info):
        # Send message to the active channel

        await self.send(
            dict_to_json({
                'type': 'info',
                'message': dict_info
            })
        )

    async def channel_400(self, details):
        """
        Raise socket exception and
        send back response to the channel
        :param details:
        :return:
        """
        # Send message to the active channel
        await self.send_back_response(details, 400)
        raise SocketException(details)

    async def send_back_response(self, details, status_code):
        # Send message to the active channel

        await self.send(
            dict_to_json({
                'type': 'response',
                'message': {
                    'status': status_code,
                    'data': details
                }
            })
        )

    async def view_response(self, response: ConsumerResponse, source=None):
        # Send message to the active channel

        await self.send(dict_to_json(
            {
                'type': 'response',
                'message': {
                    'source': source,
                    'status_code': response.status,
                    'data': response.data
                }
            }
        ))

    async def view_response_gp(self, response: ConsumerResponse, gp_name, source=None):
        # Send message to the active channel

        await self.channel_layer.group_send(
            gp_name,
            {
                'type': 'response',
                'message': {
                    'source': source,
                    'status_code': response.status,
                    'data': response.data
                }
            }
        )

    async def get_request(self, text_data):
        """
        Extract request text_data and make request object
        :param text_data:
        :return:
        """
        try:
            text_data_json = json.loads(text_data)
            request = text_data_json.get('request', {})

            # request object check
            if not request.get('endpoint'):
                await self.channel_400(_("'endpoint' must be specified"))
            if 'data' not in request.keys():
                await self.channel_400(_("'data' must be specified"))
            if 'headers' not in request.keys():
                await self.channel_400(_("'headers' must be specified"))
            if not request.get('method'):
                await self.channel_400(_("'method' must be specified"))

            return request

        except JSONDecodeError as e:
            await self.channel_400(str(e))

    async def info(self, event):
        message = event.get('message', {})
        response = {'message': message}
        text_data = dict_to_json(response)
        await self.send(text_data=text_data)

    async def response(self, event):
        message = event.get('message', {})
        response = {'message': message}
        text_data = dict_to_json(response)
        await self.send(text_data=text_data)

    @database_sync_to_async
    def db_get(self, base_class, **kwargs):
        return base_class.objects.get(**kwargs)
