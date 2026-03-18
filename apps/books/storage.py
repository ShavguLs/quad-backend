"""Storage backends for the books app."""
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateMediaStorage(FileSystemStorage):
    """
    Storage backend for private files not accessible via direct URL.
    
    In production (S3-compatible credentials set): Uses remote object storage.
    In local development: Uses filesystem storage.
    """
    
    _s3_storage = None
    
    def __init__(self, **kwargs):
        # Determine if we should use remote object storage
        self.use_s3 = bool(
            settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY
        )
        
        if self.use_s3:
            # S3 storage - initialize parent with S3 parameters
            try:
                from storages.backends.s3boto3 import S3Boto3Storage
                storage_kwargs = {
                    'bucket_name': settings.AWS_STORAGE_BUCKET_NAME,
                    'region_name': settings.AWS_S3_REGION_NAME,
                    'default_acl': None,
                    'file_overwrite': getattr(settings, 'AWS_S3_FILE_OVERWRITE', False),
                }

                endpoint_url = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
                signature_version = getattr(settings, 'AWS_S3_SIGNATURE_VERSION', None)
                addressing_style = getattr(settings, 'AWS_S3_ADDRESSING_STYLE', None)

                if endpoint_url:
                    storage_kwargs['endpoint_url'] = endpoint_url
                if signature_version:
                    storage_kwargs['signature_version'] = signature_version
                if addressing_style:
                    storage_kwargs['addressing_style'] = addressing_style

                self._s3_storage = S3Boto3Storage(**storage_kwargs)
                # Don't call super().__init__ since we're using _s3_storage
            except ImportError:
                # Fallback to filesystem if storages not installed
                self.use_s3 = False
                kwargs.setdefault('location', getattr(settings, 'PRIVATE_MEDIA_ROOT', None))
                super().__init__(**kwargs)
        else:
            # Filesystem storage
            kwargs.setdefault('location', getattr(settings, 'PRIVATE_MEDIA_ROOT', None))
            super().__init__(**kwargs)
    
    def _get_storage(self):
        """Get the underlying storage backend."""
        if self.use_s3 and self._s3_storage:
            return self._s3_storage
        return self
    
    def url(self, name):
        """Direct URLs are intentionally disabled for private media."""
        return ''
    
    def get_available_name(self, name, max_length=None):
        """Generate unique filename using UUID."""
        ext = Path(name).suffix
        filename = f"{uuid.uuid4().hex}{ext}"
        storage = self._get_storage()
        if storage is self:
            return super().get_available_name(filename, max_length)
        return storage.get_available_name(filename, max_length)
    
    def save(self, name, content, max_length=None):
        """Save file to storage."""
        storage = self._get_storage()
        if storage is self:
            return super().save(name, content, max_length)
        return storage.save(name, content, max_length)
    
    def open(self, name, mode='rb'):
        """Open file from storage."""
        storage = self._get_storage()
        if storage is self:
            return super().open(name, mode)
        return storage.open(name, mode)
    
    def delete(self, name):
        """Delete file from storage."""
        storage = self._get_storage()
        if storage is self:
            return super().delete(name)
        return storage.delete(name)
    
    def exists(self, name):
        """Check if file exists in storage."""
        storage = self._get_storage()
        if storage is self:
            return super().exists(name)
        return storage.exists(name)
    
    def size(self, name):
        """Get file size from storage."""
        storage = self._get_storage()
        if storage is self:
            return super().size(name)
        return storage.size(name)
    
    def path(self, name):
        """Get local filesystem path (only for filesystem storage)."""
        if self.use_s3:
            # S3 doesn't have a local path
            raise NotImplementedError("This storage doesn't support absolute paths.")
        return super().path(name)
