"""Custom permissions for the social app."""

from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Allow read-only access for anyone; write access only for owners.

    Supports models using either `user` or `author` ownership fields.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        owner = getattr(obj, "user", None) or getattr(obj, "author", None)
        return owner == request.user


class IsAuthor(permissions.BasePermission):
    """
    Permission that checks if the user is the author of the book
    being reviewed (can reply to reviews on their books).
    """

    def has_permission(self, request, view):
        # For create, check if user owns the book being reviewed
        if request.method == 'POST':
            review_id = view.kwargs.get('review_pk') or request.data.get('review')
            if review_id:
                from .models import Review
                try:
                    review = Review.objects.select_related('book').get(pk=review_id)
                    return review.book.owner == request.user
                except Review.DoesNotExist:
                    return False
        return True

    def has_object_permission(self, request, view, obj):
        # For update/delete, check if user is the reply author
        return obj.author == request.user
