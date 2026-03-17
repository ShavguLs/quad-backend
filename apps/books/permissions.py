"""
Custom permissions for the books app.
"""

from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of a book to edit or delete it.
    
    - Safe methods (GET, HEAD, OPTIONS) are allowed for anyone
    - Unsafe methods (POST, PUT, PATCH, DELETE) require ownership
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner
        return obj.owner == request.user
