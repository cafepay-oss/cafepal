from abc import ABC

from django.utils.translation import gettext as _
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission

from cafepay.api_v1.consumers.helpers import ConsumerException, MODIFY_METHODS, WATCH, get_object_or_404


class NotImplementedConsumer(ConsumerException):
    pass


class Path:
    """
        A route
        maps name to a view function
    """

    paths_list = []

    def __init__(self, pattern, view, name=None):
        self.pattern = pattern
        self.view = view
        self.name = name

    @staticmethod
    def arg(term):
        """
        Check if the given term is an argument
        :param term:
        :return: the argument if term is argument, false otherwise
        """
        if len(term) < 3:
            return False
        if term[0] == "<" and term[-1] == ">":
            return term.replace("<", "").replace(">", "")

    def get_arg_names(self):
        """
        :return: pattern argument names
        """

        args = []

        for term in self.pattern.split("/"):
            the_arg = Path.arg(term)
            if the_arg:
                args += [the_arg]

        return args

    @staticmethod
    def reverse(name, kwargs={}):
        """return path url by path name and kwargs"""
        the_path = None
        for consumer_path in Path.paths_list:
            if consumer_path.name == name:
                the_path = consumer_path
                break

        if not the_path:
            raise Exception(_("Path name not fund"))

        url = the_path.pattern

        for arg in the_path.get_arg_names():
            url = url.replace(arg, str(kwargs[arg]))

        return url.replace('<', '').replace('>', '')

    @staticmethod
    def match(target):
        """
        :param target:
        :return: match the given target path with a consumer path
                 return kwargs and the corresponding view
        """
        kwargs = {}

        target_terms = target.split("/")

        for consumer_path in Path.paths_list:
            path_terms = consumer_path.pattern.split("/")

            if len(path_terms) != len(target_terms):
                continue

            found = True

            for i in range(len(path_terms)):
                if Path.arg(path_terms[i]):
                    kwargs[Path.arg(path_terms[i])] = target_terms[i]
                elif path_terms[i] != target_terms[i]:
                    kwargs = {}
                    found = False
                    break
            if found:
                return consumer_path.view, kwargs

        raise ConsumerException(_("Endpoint not found: %s" % target))

    @staticmethod
    def flatten(absolute_path):
        return absolute_path.replace("/", ".")

    @staticmethod
    def normalize(flatten_path):
        return flatten_path.replace('.', "/")


def path(pattern, view, name=None):
    """
    Create a consumer path
    :param pattern:
    :param view:
    :param name:
    :return: consumer path
    """

    Path.paths_list += [Path(pattern, view, name)]


class ConsumerRequest:
    """
        Request object to be passed to consumer views
    """

    def __init__(self, data, method, user,
                 scope, channel_name, channel_layer,
                 request_endpoint, dispatcher):
        self.data = data
        self.method = method
        self.user = user
        self.scope = scope
        self.channel_name = channel_name
        self.channel_layer = channel_layer
        self.request_endpoint = request_endpoint
        self.dispatcher = dispatcher

    def build_absolute_uri(self, location=None):
        if self.scope.get('server'):
            host = str(self.scope.get('server')[0]) + ':' + str(self.scope.get('server')[1])
            host += "//"
            return host + location
        else:
            host = self.scope.get('headers')[2][1].decode('utf-8') + '//'
            return 'https://' + host + location



class ConsumerResponse:
    """
        Consumer Response structure
    """

    def __init__(self, data={}, status=200):
        self.status = status
        self.data = data


class BaseConsumerView(ABC):
    """
        Abstract Consumer View
    """

    queryset = None
    serializer_class = None
    permission_classes = None

    lookup_field = 'pk'
    lookup_url_kwarg = None

    affected_method_paths = None

    def __init__(self):
        self.kwargs = {}
        self.request = None

    @classmethod
    def as_view(cls):
        return cls()._as_view

    def _init_(self, request: ConsumerRequest, **kwargs):
        """
        Check permissions, dispatch the proper view function based on method
        :param request:
        :param kwargs:
        :return: view function
        """

        self.kwargs = kwargs
        self.request = request

        # check permission
        for permission in self.get_permissions():

            if not permission.has_permission(request, self):
                raise ConsumerException(_("Permission Denied"))

        # get affected consumer views
        paths = []
        affected_paths = self.get_affected_method_paths()

        if affected_paths:
            for affected_path in affected_paths:
                assert type(affected_path) == \
                       MethodPathEffect, "TypeError affect consumer classes" \
                                         " must be an instance of MethodAffectConsumer"
                if request.method in affected_path.methods:
                    paths += [affected_path.absolute_path]

        # if request is watch, add the current channel to the endpoint group
        if request.method == WATCH:
            watcher = WatcherList(view=self, request=request, kwargs=kwargs)
            WatcherList.add(watcher)

        return self.dispatch(request.method), paths, self

    async def _as_view(self, request: ConsumerRequest, bypass_permissions=False, **kwargs):

        assert type(request) == ConsumerRequest, \
            "request type must be ConsumerRequest not %s" % type(request)

        # create a new view instance
        _view = self.__class__()._init_(request, **kwargs)

        return _view

    def get_affected_method_paths(self):
        """
        :return: Classes that the execution of the this view affects
        """

        return self.affected_method_paths

    def get_watch_gp_name(self):
        return Path.flatten(self.request.request_endpoint)

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        permissions = []

        if not self.permission_classes:
            return []

        for permission_class in self.permission_classes:
            assert issubclass(permission_class, BasePermission), \
                "permission must be of type BasePermission not %s" % type(permission_class)
            permissions += [permission_class()]

        return permissions

    def dispatch(self, method):
        """
        :param method:
        :return: proper view function based on method
        """
        _dispatch = {
            'get': self.get, 'post': self.post, 'watch': self.get,
            'put': self.put, 'delete': self.delete
        }

        return _dispatch[method.lower()]

    def get_queryset(self):
        if not self.queryset:
            raise NotImplementedConsumer(_("You should either set queryset or override get_queryset"))

        return self.queryset

    def get_serializer_class(self):

        if not self.serializer_class:
            raise NotImplementedConsumer(_("You should either set serializer_class or override get_serializer_class"))

        return self.serializer_class

    def get_serializer_context(self):
        return {
            'request': self.request,
            'view': self
        }

    def get_serializer(self, *args, **kwargs):

        serializer_class = self.get_serializer_class()
        kwargs['context'] = self.get_serializer_context()
        return serializer_class(*args, **kwargs)

    async def get(self, request, *args, **kwargs):
        raise NotImplementedConsumer(_("GET method not implemented"))

    async def post(self, request, *args, **kwargs):
        raise NotImplementedConsumer(_("POST method not implemented"))

    async def put(self, request, *args, **kwargs):
        raise NotImplementedConsumer(_("PUT method not implemented"))

    async def delete(self, request, *args, **kwargs):
        raise NotImplementedConsumer(_("DELETE method not implemented"))


class MethodPathEffect:
    """
        Map of methods that have an effect on the api view
    """

    def __init__(self, absolute_path, methods=MODIFY_METHODS):
        self.methods = methods
        self.absolute_path = absolute_path


class WatcherList:
    watcher_list_gp_name_based = {}
    watcher_list_channel_based = {}

    def __init__(self, view, request: ConsumerRequest, kwargs):
        self.view = view
        self.request = request
        self.kwargs = kwargs

    @staticmethod
    def add(watcher):
        gp_name = watcher.view.get_watch_gp_name()

        if gp_name not in WatcherList.watcher_list_gp_name_based.keys():
            WatcherList.watcher_list_gp_name_based[gp_name] = set()

        WatcherList.watcher_list_gp_name_based[gp_name].add(watcher)
        watcher.request.dispatcher.groups += [gp_name, ]
        watcher.request.dispatcher.watchers += [watcher, ]

    @staticmethod
    def remove(watcher):
        gp_name = watcher.view.get_watch_gp_name()

        if gp_name not in WatcherList.watcher_list_gp_name_based.keys():
            return
        WatcherList.watcher_list_gp_name_based[gp_name].remove(watcher)

    @staticmethod
    def remove_by_channel_name(channel_name):
        # for gp in WatcherList.watcher_list_gp_name_based
        pass

    @staticmethod
    def members(gp_name):
        return WatcherList.watcher_list_gp_name_based.get(gp_name, set())

    async def execute(self):
        result = await self.view.get(self.request, self.kwargs)
        return result
        await self.request.dispatcher.view_response(result, source=self.view.get_watch_gp_name())


class ConsumerCreateAPIView(BaseConsumerView):

    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            return ConsumerResponse(serializer.data, status=status.HTTP_201_CREATED)
        except serializers.ValidationError as e:
            raise ConsumerException(e)

    def perform_create(self, serializer):
        serializer.save()

    async def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)


class ConsumerListAPIView(BaseConsumerView):

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return ConsumerResponse(serializer.data)

    async def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class ConsumerRetrieveAPIView(BaseConsumerView):
    def get_object(self):
        """
        Returns the object the view is displaying.

        You may want to override this if you need to provide non-standard
        queryset lookups.  Eg if objects are referenced using multiple
        keyword arguments in the url conf.
        """

        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        queryset = self.get_queryset()

        assert lookup_url_kwarg in self.kwargs, (
                'Expected view %s to be called with a URL keyword argument '
                'named "%s". Fix your URL conf, or set the `.lookup_field` '
                'attribute on the view correctly.' %
                (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        return obj

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return ConsumerResponse(serializer.data)

    async def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)
