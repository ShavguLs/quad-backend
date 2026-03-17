"""
Exceptions for the publish module.

These exceptions provide specific error types for publish failures,
enabling proper error handling and user-facing messages.
"""


class PublishError(Exception):
    """
    Base exception for publish failures.
    
    Raised when a publish operation fails due to invalid state,
    authorization issues, or unexpected errors.
    
    Attributes:
        message: Human-readable error description
    """
    
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)
    
    def __str__(self) -> str:
        return self.message


class DraftChangedError(PublishError):
    """
    Raised when draft is modified during publish operation.
    
    This exception indicates that the book's draft content changed
    between the start of the publish process and the final commit.
    The user should be prompted to retry the publish operation.
    
    Attributes:
        message: Human-readable error description (defaults to standard message)
    """
    
    DEFAULT_MESSAGE = "Draft was modified during publish. Please retry."
    
    def __init__(self, message: str = None):
        self.message = message or self.DEFAULT_MESSAGE
        super().__init__(self.message)
    
    def __str__(self) -> str:
        return self.message
