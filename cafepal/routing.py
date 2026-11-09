from channels.routing import URLRouter
from cafepay.api_v1.routing import websocket_urlpatterns

from channels.routing import ProtocolTypeRouter


class CustomSocketioProtocolTypeRouter(ProtocolTypeRouter):
    """
    Overrided base class's __call__ method to support python socketio 4.2.0 and daphne 2.3.0
    """
    def __call__(self, scope, *args):
        if scope["type"] in self.application_mapping:
            handlerobj = self.application_mapping[scope["type"]](scope)
            if args:
                return handlerobj(*args)
            return handlerobj
        raise ValueError(
            "No application configured for scope type %r" % scope["type"]
        )


application = CustomSocketioProtocolTypeRouter({
    # Empty for now (http->django views is added by default)
    'websocket': URLRouter(
            websocket_urlpatterns
        )
})
