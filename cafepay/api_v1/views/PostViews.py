from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from cafepay.models import Cafe, Post, Comment, Like
from cafepay.api_v1.permissions import CanManagePost, CanManageComment, CanCreatePost, IsLoggedIn
from cafepay.api_v1.serializers.PostSerializers import PostSerializer, CommentSerializer, LikeSerializer


class PostCreateView(generics.CreateAPIView):
    """
        Create new post

        CanCreatePost permission
    """

    permission_classes = (CanCreatePost,)
    serializer_class = PostSerializer

    def perform_create(self, serializer):
        serializer.save(cafe=get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id')),
                        staff=self.request.user.user_profile)


class PostRetrieveUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    """
        Post retrieve update delete

        do not send image field when updating

        No permission required for GET

        Can manage post for update delete
    """

    permission_classes = (CanManagePost,)
    queryset = Post.objects.all()
    serializer_class = PostSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'post_id'

    def perform_update(self, serializer):
        serializer.save(staff=self.request.user.user_profile)


class PostListView(generics.ListAPIView):
    """
        List of cafe posts

    """

    serializer_class = PostSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.posts.all()


class CommentCreateView(generics.CreateAPIView):
    """
        comment on post

        Any authenticated user may comment on any post
    """

    permission_classes = (IsLoggedIn,)
    serializer_class = CommentSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user.user_profile)


class CommentRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """
        Retrieve Update Delete Comment

        only the one who made comment can manage it
    """

    permission_classes = (CanManageComment,)
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer

    lookup_field = 'pk'
    lookup_url_kwarg = 'comment_id'


class CommentListView(generics.ListAPIView):
    """
        List of all comments of a post

    """

    serializer_class = CommentSerializer

    def get_queryset(self):
        post = get_object_or_404(Post, pk=self.kwargs.get('post_id'))
        return post.comments.all()


class LikeListView(generics.ListAPIView):
    """
        List of all comments of a post

    """

    serializer_class = LikeSerializer

    def get_queryset(self):
        post = get_object_or_404(Post, pk=self.kwargs.get('post_id'))
        return post.likes.all()


class ToggleLikeView(generics.CreateAPIView):
    """
        like a post

    """
    permission_classes = (IsLoggedIn,)
    serializer_class = LikeSerializer

    def perform_create(self, serializer):
        serializer.save(post=get_object_or_404(Post, pk=self.kwargs.get('post_id')),
                        user=self.request.user.user_profile)
