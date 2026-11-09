import asyncio

from django.http.response import Http404
from rest_framework.exceptions import APIException

from cafepay.api_v1.consumers.BasicConsumer import BasicConsumer
from cafepay.api_v1.consumers.helpers import SocketException, ConsumerException
from .ConsumerView import Path, ConsumerRequest, WatcherList, ConsumerResponse
from .paths import paths
# load all consumer paths
# noinspection PyStatementEffect
from ..helpers import APIBadRequest

paths


class DispatchConsumer(BasicConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.watchers = []

    @staticmethod
    async def execute_watcher(gp_name):
        # notify the watchers
        gp_name = Path.flatten(gp_name)
        members = WatcherList.members(gp_name).copy()
        for member in members:
            # create a result generator to be used in a dispatcher consumer
            # to generate consistent responses
            async def _result_generator(request, **kwargs):
                return await member.execute()

            await DispatchConsumer.send_result(dispatcher=member.request.dispatcher, source=gp_name,
                                               request=member.request,
                                               result_generator=_result_generator)

    @staticmethod
    async def notify_watcher_endpoint(endpoint_path):
        """flatten Endpoint path is it's watcher gp name"""
        gp_name = Path.flatten(endpoint_path)
        await DispatchConsumer.execute_watcher(gp_name)

    @staticmethod
    async def send_result(dispatcher, source, result_generator, request, **kwargs):
        """calls a result generator and catches api bad request exceptions and sends
        appropriate response
        this function is used to create consistent response objects when results
        are generated in different places
        """

        try:
            result = await result_generator(request, **kwargs)
            await dispatcher.view_response(result, source=source)
        except APIBadRequest as e:
            await dispatcher.view_response(ConsumerResponse({}, e.status_code),
                                           source=source)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            raw_request = await self.get_request(text_data)
            view, kwargs = Path.match(raw_request.get('endpoint'))
            authorization = raw_request.get('headers').get('Authorization')

            # get the user
            if not authorization:
                user = None
            else:
                user = await self.authenticate(authorization)

            # create ConsumerRequest object
            request = ConsumerRequest(data=raw_request.get('data'), method=raw_request.get('method'),
                                      user=user, scope=self.scope, channel_name=self.channel_name,
                                      channel_layer=self.channel_layer, dispatcher=self,
                                      request_endpoint=raw_request.get('endpoint'))

            method_function, affected_consumer_apis, view_obj = await view(request, **kwargs)

            # report if APIBadRequest happens

            # result = await method_function(request, **kwargs)
            await self.send_result(dispatcher=self,
                                   source=view_obj.get_watch_gp_name(),
                                   request=request,
                                   result_generator=method_function,
                                   **kwargs)

            # notify the watchers
            for affected_consumer_api in affected_consumer_apis:
                await self.notify_watcher_endpoint(affected_consumer_api)

        except (ConsumerException, Http404) as e:
            await self.send_back_response(str(e), 400)
        except APIException as e:
            await self.send_back_response(str(e), e.status_code)
        except SocketException:
            """
                Socket exceptions are meat to stop the code
                proper error handling must be done before throwing this exception
            """

            pass

    async def connect(self):
        # accept any incoming connections
        self.groups = []
        self.watchers = []

        await self.accept()

    async def disconnect(self, code):
        for watcher in self.watchers:
            WatcherList.remove(watcher)

