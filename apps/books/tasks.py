import io
import html
import logging
import os
import tempfile
from typing import Optional, Union

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from apps.books.converters import EPUBConverter, PDFConverter
from apps.books.converters.base import ConversionError
from apps.books.diagnostics.service import build_diagnostics_report
from apps.books.models import Book, BookContent, BookFile, ExtractedImage
from apps.books.publish.exceptions import PublishError
from apps.books.storage import PrivateMediaStorage

# Import extraction components (added by Plan 35-02/35-03)
from apps.books.extraction.engine import ExtractionEngine, ExtractionResult
from apps.books.extraction.image_extractor import ImageExtractor, ExtractedImage as ExtractedImageData
from apps.books.extraction.confidence import ConfidenceCalculator

# Import content integration service (added by Plan 36-03)
from apps.books.services.extraction_integration import ExtractionToContentService


logger = logging.getLogger(__name__)


def _resolve_converter(mime_type):
    for converter in (PDFConverter(), EPUBConverter()):
        if converter.supports(mime_type):
            return converter
    return None


def _build_content_blocks_from_page(page_data: dict, page_number: int) -> list[dict]:
    """Build minimal valid BookContent blocks from converter page payload."""
    text = (page_data.get('text_content') or '').strip()
    if not text:
        text = ' '

    return [
        {
            'id': f'blk_{page_number}_0',
            'type': 'paragraph',
            'text': text,
            'metadata': {
                'source': 'import',
                'confidence': 1.0,
            },
        }
    ]


def _build_reader_blocks_from_page(page_data: dict, page_number: int, book_id: int) -> list[dict]:
    """
    Build reader-ready blocks from converter page output.

    Stores render payload in block metadata for fast reader responses.
    """
    html_content = (page_data.get('html_content') or '').strip()
    text_content = (page_data.get('text_content') or '').strip()
    image_data = page_data.get('image_data')

    render_mode = 'html' if html_content else 'image'
    fallback_image_path = None

    if render_mode == 'image' and image_data:
        storage = PrivateMediaStorage()
        fallback_image_path = storage.save(
            f'reader_fallback/{book_id}/{page_number:04d}.jpg',
            ContentFile(image_data),
        )

    if not html_content:
        # If HTML is missing, derive simple paragraph HTML from text.
        safe_text = html.escape(text_content) if text_content else ''
        html_content = f'<p>{safe_text}</p>'

    normalized_text = text_content or strip_tags(html_content).strip()
    page_width = page_data.get('page_width')
    page_height = page_data.get('page_height')

    try:
        page_width = float(page_width)
    except (TypeError, ValueError):
        page_width = None

    try:
        page_height = float(page_height)
    except (TypeError, ValueError):
        page_height = None

    if page_width is not None and page_width <= 0:
        page_width = None
    if page_height is not None and page_height <= 0:
        page_height = None

    return [
        {
            'id': f'reader_blk_{page_number}_0',
            'type': 'paragraph',
            'text': normalized_text,
            'metadata': {
                'source': 'extraction',
                'confidence': 1.0 if render_mode == 'html' else 0.7,
                'render_mode': render_mode,
                'render_html': html_content,
                'fallback_image_path': fallback_image_path,
                'page_width': page_width,
                'page_height': page_height,
            },
        }
    ]


def _is_local_storage(storage: Storage) -> bool:
    """
    Check if storage backend is local filesystem storage.
    
    Uses duck typing instead of class name checking for robustness.
    """
    storage_module = storage.__class__.__module__
    storage_name = storage.__class__.__name__
    
    # Check for Django's built-in FileSystemStorage
    if 'FileSystemStorage' in storage_name:
        return True
    
    # Check module path
    if 'django.core.files.storage' in storage_module:
        return True
    
    # Check for local filesystem path attribute (only local storage has this)
    if hasattr(storage, 'base_location') or hasattr(storage, 'location'):
        return True
    
    return False


def _is_remote_storage(storage: Storage) -> bool:
    """
    Check if storage backend is remote storage (S3, etc).
    """
    storage_module = storage.__class__.__module__
    storage_name = storage.__class__.__name__
    
    if 'S3Boto3Storage' in storage_name or 's3' in storage_module.lower():
        return True
    if 'boto3' in storage_module.lower():
        return True
    
    return False


def _read_file_from_storage(
    book_file: BookFile,
    draft_id: int,
    max_retries: int = 3
) -> bytes:
    """
    Read file content from storage backend with retry logic.
    
    Handles both local filesystem and S3 storage with proper
    error handling and retry logic for transient failures.
    
    Args:
        book_file: The BookFile instance containing the file
        draft_id: The draft book ID for logging
        max_retries: Maximum number of retry attempts for remote storage
        
    Returns:
        File content as bytes
        
    Raises:
        ConversionError: If file cannot be read
    """
    import time
    
    storage = book_file.file.storage
    file_path = book_file.file.name
    storage_class = storage.__class__.__name__
    storage_module = storage.__class__.__module__
    
    logger.info(
        'Reading file for draft %s: path=%s, storage=%s.%s',
        draft_id,
        file_path,
        storage_module,
        storage_class,
    )
    
    # Determine storage type using duck typing
    is_local = _is_local_storage(storage)
    is_remote = _is_remote_storage(storage)
    
    logger.info(
        'Storage type detection for draft %s: is_local=%s, is_remote=%s',
        draft_id,
        is_local,
        is_remote
    )
    
    last_exception = None
    for attempt in range(max_retries):
        try:
            # S3 storage.open() just works - no special handling needed
            with book_file.file.open('rb') as f:
                content = f.read()
            
            logger.info(
                'Read file for draft %s: %d bytes (attempt %d/%d)',
                draft_id,
                len(content),
                attempt + 1,
                max_retries
            )
            return content
            
        except FileNotFoundError as e:
            # File not found - might be eventual consistency with S3
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    'File not found (attempt %d/%d), '
                    'waiting %ds for eventual consistency: %s',
                    attempt + 1,
                    max_retries,
                    wait_time,
                    file_path
                )
                time.sleep(wait_time)
                continue
            else:
                logger.error(
                    'File not found after %d attempts: %s',
                    max_retries,
                    file_path
                )
                raise ConversionError(
                    f'File not found: {file_path}. '
                    f'File may not have been uploaded successfully.'
                ) from e
                
        except Exception as e:
            last_exception = e
            # Network or other error - retry
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(
                    'Error reading file (attempt %d/%d), '
                    'retrying in %ds: %s',
                    attempt + 1,
                    max_retries,
                    wait_time,
                    e
                )
                time.sleep(wait_time)
                continue
            logger.error(
                'Failed to read file after %d attempts '
                'for draft %s: %s',
                max_retries,
                draft_id,
                e
            )
            raise ConversionError(
                f'Failed to download file: {file_path}. Error: {e}'
            ) from e
    
    # Should never reach here
    raise ConversionError(
        f'Failed to read file: {file_path}. '
        f'Last error: {last_exception}'
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_book_upload_task(self, book_id: int):
    """
    Async pipeline for uploaded source files.

    Converts uploaded PDFs/EPUBs into reader-ready BookContent pages and
    updates extraction/readability status.
    """
    try:
        with transaction.atomic():
            book = Book.objects.select_for_update().get(pk=book_id)
            now = timezone.now()
            book.extraction_status = 'processing'
            book.extraction_error = None
            book.extraction_started_at = now
            book.extraction_updated_at = now
            book.extraction_finished_at = None
            book.is_visible = False
            book.save(
                update_fields=[
                    'extraction_status',
                    'extraction_error',
                    'extraction_started_at',
                    'extraction_updated_at',
                    'extraction_finished_at',
                    'is_visible',
                    'updated_at',
                ]
            )

        book = Book.objects.get(pk=book_id)
        book_file = BookFile.objects.filter(book_id=book_id).order_by('-uploaded_at').first()
        if book_file is None:
            raise ConversionError('No uploaded source file available.')

        converter = _resolve_converter(book_file.mime_type)
        if converter is None:
            raise ConversionError(f'Unsupported file type for conversion: {book_file.mime_type}')

        file_content_bytes = _read_file_from_storage(book_file, book_id)
        file_content = io.BytesIO(file_content_bytes)

        try:
            pages = converter.convert(file_content, book)
        finally:
            file_content.close()

        # Replace content for latest upload.
        book.content_pages.all().delete()

        pages_created = 0
        page_failures = []
        for page_data in pages:
            try:
                page_number = int(page_data.get('page_number') or pages_created + 1)
                blocks = _build_reader_blocks_from_page(page_data, page_number, book_id)
                BookContent.objects.create(
                    book=book,
                    page_number=page_number,
                    blocks=blocks,
                    version=1,
                )
                pages_created += 1
            except Exception as page_exc:
                page_failures.append(f'page {page_data.get("page_number")}: {page_exc}')

        now = timezone.now()
        if pages_created == 0:
            raise ConversionError('Extraction produced zero readable pages.')

        extraction_status = 'partial' if page_failures else 'completed'
        extraction_error = None
        if page_failures:
            extraction_error = '; '.join(page_failures[:5])

        Book.objects.filter(pk=book_id).update(
            total_pages=pages_created,
            extraction_status=extraction_status,
            extraction_error=extraction_error,
            extraction_pages_processed=pages_created,
            extraction_finished_at=now,
            extraction_updated_at=now,
            is_visible=Book.objects.filter(pk=book_id, status='published').exists(),
            updated_at=now,
        )

        logger.info(
            'Upload extraction complete for book %s: %s (%s pages)',
            book_id,
            extraction_status,
            pages_created,
        )
        return {
            'book_id': book_id,
            'status': extraction_status,
            'pages_created': pages_created,
        }

    except Book.DoesNotExist:
        logger.warning('Book %s missing, upload task skipped', book_id)
        return {'book_id': book_id, 'status': 'missing'}

    except ConversionError as exc:
        now = timezone.now()
        Book.objects.filter(pk=book_id).update(
            extraction_status='failed',
            extraction_error=str(exc),
            extraction_finished_at=now,
            extraction_updated_at=now,
            is_visible=False,
            updated_at=now,
        )
        logger.warning('Upload extraction failed for %s: %s', book_id, exc)
        return {'book_id': book_id, 'status': 'failed', 'error': str(exc)}

    except Exception as exc:
        now = timezone.now()
        error_msg = f'{type(exc).__name__}: {exc}'
        Book.objects.filter(pk=book_id).update(
            extraction_status='failed',
            extraction_error=error_msg,
            extraction_finished_at=now,
            extraction_updated_at=now,
            is_visible=False,
            updated_at=now,
        )
        logger.exception('Unexpected upload extraction failure for %s', book_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        return {'book_id': book_id, 'status': 'failed', 'error': error_msg}


@shared_task(bind=True, max_retries=3)
def process_draft_intake(self, draft_id):
    """
    Process draft intake asynchronously with durable lifecycle updates.
    
    Implements retry logic for transient failures and comprehensive error
    handling for production debugging.
    """
    try:
        with transaction.atomic():
            draft = Book.objects.select_for_update().get(pk=draft_id)
            if draft.status != 'draft' or draft.intake_status != 'queued':
                logger.info(
                    'Skipping intake task for draft %s because status=%s intake_status=%s',
                    draft_id,
                    draft.status,
                    draft.intake_status,
                )
                return {'draftId': draft_id, 'status': 'skipped'}

            now = timezone.now()
            draft.intake_status = 'processing'
            draft.intake_error = None
            draft.intake_updated_at = now
            draft.intake_finished_at = None
            draft.save(
                update_fields=[
                    'intake_status',
                    'intake_error',
                    'intake_updated_at',
                    'intake_finished_at',
                    'updated_at',
                ]
            )

        draft = Book.objects.get(pk=draft_id)
        book_file = BookFile.objects.filter(book_id=draft_id).order_by('-uploaded_at').first()
        if book_file is None:
            raise ConversionError('No uploaded intake file available for this draft.')

        converter = _resolve_converter(book_file.mime_type)
        if converter is None:
            raise ConversionError(f'Unsupported file type for conversion: {book_file.mime_type}')

        # Clean up existing structured content before conversion
        draft.content_pages.all().delete()

        # Read file from storage with retry logic
        file_content_bytes = _read_file_from_storage(book_file, draft_id)
        file_content = io.BytesIO(file_content_bytes)

        intake_diagnostics = []
        processed_pages = 0
        content_pages_created = 0

        try:
            if book_file.mime_type in {'application/pdf', 'application/x-pdf'}:
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                        temp_file.write(file_content_bytes)
                        temp_path = temp_file.name

                    extraction_engine = ExtractionEngine()
                    extraction_result = extraction_engine.extract(temp_path, book_id=draft.id)

                    created_content_pages = ExtractionToContentService.create_content_from_extraction(
                        draft,
                        extraction_result,
                    )

                    content_pages_created = len(created_content_pages)
                    processed_pages = extraction_result.total_pages or content_pages_created

                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
            else:
                pages = converter.convert(file_content, draft)

                # Capture diagnostics from converter if available
                if hasattr(converter, 'get_unsupported_styles'):
                    unsupported_styles = converter.get_unsupported_styles()
                    if unsupported_styles:
                        report = build_diagnostics_report(unsupported_styles)
                        intake_diagnostics = report.to_dict()

                for page_data in pages:
                    page_number = int(page_data.get('page_number') or content_pages_created + 1)
                    blocks = _build_content_blocks_from_page(page_data, page_number)
                    BookContent.objects.create(
                        book=draft,
                        page_number=page_number,
                        blocks=blocks,
                        version=1,
                    )
                    content_pages_created += 1

                processed_pages = len(pages)
        finally:
            file_content.close()

        now = timezone.now()
        Book.objects.filter(pk=draft_id).update(
            total_pages=processed_pages,
            intake_status='ready',
            intake_error=None,
            extraction_status='completed',
            extraction_error=None,
            extraction_pages_processed=content_pages_created,
            extraction_finished_at=now,
            extraction_updated_at=now,
            intake_finished_at=now,
            intake_updated_at=now,
            intake_diagnostics=intake_diagnostics.get('items', []) if intake_diagnostics else [],
            updated_at=now,
        )
        
        logger.info(
            'Draft intake completed successfully for draft %s: %d pages (%d content pages created)',
            draft_id,
            processed_pages,
            content_pages_created
        )
        
        return {'draftId': draft_id, 'status': 'ready', 'pages': processed_pages}

    except Book.DoesNotExist:
        logger.warning('Draft %s missing; intake task skipped', draft_id)
        return {'draftId': draft_id, 'status': 'missing'}
        
    except ConversionError as exc:
        now = timezone.now()
        Book.objects.filter(pk=draft_id).update(
            intake_status='failed',
            intake_error=str(exc),
            intake_finished_at=now,
            intake_updated_at=now,
            updated_at=now,
        )
        logger.warning('Draft intake conversion failed for %s: %s', draft_id, exc)
        
        # Retry transient failures
        if 'network' in str(exc).lower() or 'timeout' in str(exc).lower():
            if self.request.retries < self.max_retries:
                logger.info('Retrying draft %s due to transient error', draft_id)
                raise self.retry(exc=exc, countdown=30)
        
        return {'draftId': draft_id, 'status': 'failed', 'error': str(exc)}
        
    except Exception as exc:
        now = timezone.now()
        error_msg = f'Unexpected intake error: {type(exc).__name__}: {exc}'
        Book.objects.filter(pk=draft_id).update(
            intake_status='failed',
            intake_error=error_msg,
            intake_finished_at=now,
            intake_updated_at=now,
            updated_at=now,
        )
        logger.exception('Unexpected draft intake failure for %s', draft_id)
        
        # Retry on unexpected errors
        if self.request.retries < self.max_retries:
            logger.info('Retrying draft %s due to unexpected error', draft_id)
            raise self.retry(exc=exc, countdown=60)
        
        return {'draftId': draft_id, 'status': 'failed', 'error': error_msg}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def publish_book_task(self, book_id: int, user_id: int) -> dict:
    """
    Celery task to publish a book asynchronously.
    
    This avoids Heroku's 30-second web request timeout by running
    the image generation in a background worker.
    """
    from django.contrib.auth import get_user_model
    from .publish.service import PublishService
    
    User = get_user_model()
    
    try:
        book = Book.objects.get(pk=book_id)
        user = User.objects.get(pk=user_id)
        
        logger.info(f'Starting publish task for book {book_id}')
        
        # Update status to publishing
        book.publish_status = 'publishing'
        book.save(update_fields=['publish_status', 'updated_at'])
        
        # Run publish (simplified - no image generation needed for text-based publishing)
        service = PublishService()
        result = service.publish_book(book_id, user)
        
        if result.success:
            logger.info(f'Publish task completed for book {book_id}: {result.pages_published} pages')
            return {
                'bookId': book_id,
                'status': 'published',
                'pages': result.pages_published
            }
        else:
            logger.warning(f'Publish task failed for book {book_id}: {result.error_message}')
            return {
                'bookId': book_id,
                'status': 'failed',
                'error': result.error_message
            }
            
    except Book.DoesNotExist:
        logger.error(f'Book {book_id} not found for publish task')
        return {'bookId': book_id, 'status': 'failed', 'error': 'Book not found'}
    except PublishError as e:
        # Handle publish validation errors (including parity mismatches)
        logger.warning(f'Publish validation failed for book {book_id}: {e}')
        error_message = str(e)
        
        # Check if it's a parity mismatch error
        if 'rendering mismatches' in error_message:
            return {
                'bookId': book_id,
                'status': 'failed',
                'error': error_message,
                'error_type': 'PARITY_MISMATCH',
            }
        
        return {
            'bookId': book_id,
            'status': 'failed',
            'error': error_message,
        }
    except Exception as exc:
        logger.exception(f'Publish task failed for book {book_id}')
        
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            logger.info(f'Retrying publish for book {book_id}')
            raise self.retry(exc=exc, countdown=30)
        
        # Mark as failed
        try:
            Book.objects.filter(pk=book_id).update(
                publish_status='failed',
                updated_at=timezone.now()
            )
        except Exception:
            logger.exception('Failed to mark book %s publish_status=failed after task exhaustion', book_id)
            
        return {'bookId': book_id, 'status': 'failed', 'error': str(exc)}


@shared_task(
    bind=True,
    max_retries=3,
    soft_time_limit=300,  # 5 minutes soft limit
    time_limit=360,       # 6 minutes hard limit
    default_retry_delay=30
)
def extract_pdf_text_task(self, book_id: int, file_path: str) -> dict:
    """
    Extract text and images from PDF asynchronously with progress tracking.
    
    This task replaces/supplements the existing image-based extraction
    with structured text extraction for the new reader experience.
    
    Progress updates available via:
    - task.status: 'PENDING', 'PROGRESS', 'SUCCESS', 'FAILURE'
    - task.result.get('progress'): Dict with current, total, percent, stage
    
    Args:
        book_id: Book ID to process
        file_path: Path to PDF file in storage
        
    Returns:
        Dict with extraction results:
        {
            'status': 'completed' | 'partial' | 'failed',
            'book_id': int,
            'total_pages': int,
            'pages_processed': int,
            'images_extracted': int,
            'average_confidence': float,  # Placeholder for Plan 35-03
            'warnings': list,
            'error': str (if failed)
        }
    """
    from celery.exceptions import SoftTimeLimitExceeded
    from django.core.files.base import ContentFile
    
    logger.info(f"Starting text extraction for book {book_id}: {file_path}")
    
    # Track partial results for timeout handling
    results = {
        'book_id': book_id,
        'pages': [],
        'images': {},
        'confidence_scores': [],
        'warnings': [],
        'errors': []
    }
    
    try:
        # Validate PDF before extraction
        engine = ExtractionEngine()
        validation = engine.validate_pdf(file_path)
        
        if not validation['valid']:
            error_msg = f"PDF validation failed: {', '.join(validation['warnings'])}"
            logger.error(f"Book {book_id}: {error_msg}")
            
            _update_book_extraction_status(
                book_id=book_id,
                status='failed',
                error=error_msg
            )
            return {
                'status': 'failed',
                'book_id': book_id,
                'error': error_msg
            }
        
        # Log warnings from validation
        if validation['warnings']:
            results['warnings'].extend(validation['warnings'])
            logger.warning(f"Book {book_id} validation warnings: {validation['warnings']}")
        
        total_pages = validation['page_count']
        
        # Update book status to processing
        _update_book_extraction_status(
            book_id=book_id,
            status='processing',
            total_pages=total_pages
        )
        
        # Initialize extractors
        image_extractor = ImageExtractor()
        doc = None
        
        try:
            import pymupdf
            doc = pymupdf.open(file_path)
            
            # Process each page
            for page_num in range(total_pages):
                try:
                    # Update progress
                    progress_pct = int((page_num / total_pages) * 100)
                    self.update_state(
                        state='PROGRESS',
                        meta={
                            'current': page_num + 1,
                            'total': total_pages,
                            'percent': progress_pct,
                            'stage': f'Extracting page {page_num + 1}/{total_pages}'
                        }
                    )
                    
                    page = doc[page_num]
                    
                    # Extract text with structure
                    extracted_page = engine.text_extractor.extract_page(
                        page, page_num + 1
                    )
                    results['pages'].append(extracted_page)
                    
                    # Extract images from this page
                    page_images = image_extractor.extract_from_page(doc, page_num)
                    if page_images:
                        results['images'][page_num + 1] = page_images
                        
                        # Save images to storage
                        _save_extracted_images(
                            book_id=book_id,
                            page_num=page_num + 1,
                            images=page_images
                        )
                    
                    # Calculate confidence for this page
                    calculator = ConfidenceCalculator()
                    confidence = calculator.calculate(
                        page=extracted_page,
                        images_extracted=page_images if page_images else [],
                        images_expected=len(page_images) if page_images else 0
                    )
                    results['confidence_scores'].append(confidence)
                    results['warnings'].extend(confidence.warnings)
                    
                    # Collect layout warnings
                    if extracted_page.layout and extracted_page.layout.warnings:
                        results['warnings'].extend(extracted_page.layout.warnings)
                        
                except Exception as e:
                    error_msg = f"Error on page {page_num + 1}: {str(e)}"
                    logger.error(f"Book {book_id}: {error_msg}")
                    results['errors'].append(error_msg)
                    # Continue with next page
                    continue
            
            # Close document
            doc.close()
            doc = None
            
            # Calculate metrics
            pages_processed = len(results['pages'])
            images_count = sum(len(imgs) for imgs in results['images'].values())
            
            # Aggregate confidence scores
            calculator = ConfidenceCalculator()
            confidence_summary = calculator.aggregate_pages(results['confidence_scores'])
            average_confidence = confidence_summary.get('overall_average', 0.0)
            
            # Create BookContent from extraction results (Plan 36-03)
            content_pages_created = 0
            content_linked = False
            content_creation_error = None
            
            try:
                logger.info(f"Creating BookContent records for book {book_id}")
                
                # Get book instance
                book = Book.objects.get(pk=book_id)
                
                # Create ExtractionResult from pages
                extraction_result = ExtractionResult(
                    book_id=book_id,
                    pages=results['pages'],
                    total_pages=total_pages,
                    confidence_scores=results['confidence_scores'],
                    warnings=results['warnings'],
                    errors=results['errors']
                )
                
                # Create content from extraction
                content_pages = ExtractionToContentService.create_content_from_extraction(
                    book=book,
                    extraction_result=extraction_result,
                    user=None  # System extraction
                )
                content_pages_created = len(content_pages)
                
                logger.info(f"Created {content_pages_created} BookContent records for book {book_id}")
                
                # Link extracted images to content blocks
                logger.info(f"Linking extracted images to content for book {book_id}")
                images_linked = ExtractionToContentService.link_extracted_images(
                    book=book,
                    extraction_result=extraction_result
                )
                content_linked = images_linked > 0
                
                logger.info(f"Linked {images_linked} images to content blocks for book {book_id}")
                
            except Exception as e:
                content_creation_error = str(e)
                logger.error(f"Failed to create BookContent for book {book_id}: {e}")
                # Don't fail the extraction, but log the error
            
            # Update book with extraction results including confidence
            _update_book_extraction_status(
                book_id=book_id,
                status='completed' if pages_processed == total_pages else 'partial',
                pages_processed=pages_processed,
                total_pages=total_pages,
                average_confidence=average_confidence,
                warnings=results['warnings'],
                errors=results['errors'],
                confidence_summary=confidence_summary,
                content_pages_created=content_pages_created,
                content_creation_error=content_creation_error
            )
            
            logger.info(
                f"Extraction completed for book {book_id}: "
                f"{pages_processed}/{total_pages} pages, "
                f"{images_count} images, "
                f"confidence={average_confidence:.2f}, "
                f"{content_pages_created} content pages, "
                f"{len(results['warnings'])} warnings"
            )
            
            return {
                'status': 'completed' if pages_processed == total_pages else 'partial',
                'book_id': book_id,
                'total_pages': total_pages,
                'pages_processed': pages_processed,
                'images_extracted': images_count,
                'content_pages_created': content_pages_created,
                'content_linked': content_linked,
                'average_confidence': average_confidence,
                'confidence_level': 'high' if average_confidence >= 0.8
                                   else 'medium' if average_confidence >= 0.5
                                   else 'low',
                'pages_with_warnings': confidence_summary.get('pages_with_warnings', 0),
                'pages_unacceptable': confidence_summary.get('pages_unacceptable', 0),
                'warnings': results['warnings'],
                'errors': results['errors'],
                'content_creation_error': content_creation_error
            }
            
        finally:
            if doc:
                doc.close()
                
    except SoftTimeLimitExceeded:
        # Handle soft timeout - save partial results
        logger.warning(f"Extraction timeout for book {book_id}")
        
        pages_processed = len(results.get('pages', []))
        confidence_scores = results.get('confidence_scores', [])
        avg_confidence = (
            sum(c.overall for c in confidence_scores) / len(confidence_scores)
            if confidence_scores else 0.0
        )
        
        _update_book_extraction_status(
            book_id=book_id,
            status='partial',
            error='Processing timeout - partial results saved',
            pages_processed=pages_processed,
            average_confidence=avg_confidence
        )
        
        return {
            'status': 'partial',
            'book_id': book_id,
            'total_pages': validation.get('page_count', 0) if 'validation' in dir() else 0,
            'pages_processed': pages_processed,
            'images_extracted': sum(len(imgs) for imgs in results.get('images', {}).values()),
            'average_confidence': round(avg_confidence, 2),
            'error': 'Processing timeout - partial results saved',
            'warnings': results.get('warnings', []),
            'errors': results.get('errors', [])
        }
        
    except Exception as exc:
        logger.exception(f"Extraction failed for book {book_id}")
        
        # Retry on transient failures
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying extraction for book {book_id} (attempt {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=60)
        
        # Final failure
        _update_book_extraction_status(
            book_id=book_id,
            status='failed',
            error=f"{type(exc).__name__}: {str(exc)}"
        )
        
        return {
            'status': 'failed',
            'book_id': book_id,
            'error': f"{type(exc).__name__}: {str(exc)}"
        }


def _update_book_extraction_status(book_id: int,
                                  status: str,
                                  error: str = None,
                                  pages_processed: int = None,
                                  total_pages: int = None,
                                  average_confidence: float = None,
                                  warnings: list = None,
                                  errors: list = None,
                                  confidence_summary: dict = None,
                                  content_pages_created: int = None,
                                  content_creation_error: str = None):
    """
    Update book extraction status in database.
    
    Helper function to centralize status update logic.
    """
    from django.utils import timezone
    
    update_fields = {
        'extraction_status': status,
        'extraction_updated_at': timezone.now()
    }
    
    if error:
        update_fields['extraction_error'] = error
    
    if pages_processed is not None:
        update_fields['extraction_pages_processed'] = pages_processed
    
    if total_pages is not None:
        update_fields['total_pages'] = total_pages
    
    # Build diagnostics
    diagnostics = []
    
    if average_confidence is not None:
        diagnostics.append({
            'type': 'confidence',
            'average': round(average_confidence, 2),
            'level': 'high' if average_confidence >= 0.8
                    else 'medium' if average_confidence >= 0.5
                    else 'low'
        })
    
    if confidence_summary:
        diagnostics.append({
            'type': 'confidence_summary',
            'metrics': {
                'text_coverage': confidence_summary.get('text_coverage_average'),
                'font_consistency': confidence_summary.get('font_consistency_average'),
                'structure_detection': confidence_summary.get('structure_detection_average'),
                'reading_order': confidence_summary.get('reading_order_average'),
            },
            'pages_with_warnings': confidence_summary.get('pages_with_warnings'),
            'pages_unacceptable': confidence_summary.get('pages_unacceptable')
        })
    
    if warnings:
        diagnostics.extend([{'type': 'warning', 'message': w} for w in warnings[:20]])  # Limit warnings
    
    if errors:
        diagnostics.extend([{'type': 'error', 'message': e} for e in errors[:10]])  # Limit errors
    
    # Add content creation diagnostics (Plan 36-03)
    if content_pages_created is not None or content_creation_error:
        content_diag = {
            'type': 'content_creation',
            'pages_created': content_pages_created or 0,
            'success': content_pages_created is not None and content_pages_created > 0,
        }
        if content_creation_error:
            content_diag['error'] = content_creation_error
        diagnostics.append(content_diag)
    
    if diagnostics:
        update_fields['extraction_diagnostics'] = diagnostics
    
    if status in ['completed', 'partial', 'failed']:
        update_fields['extraction_finished_at'] = timezone.now()
    
    Book.objects.filter(pk=book_id).update(**update_fields)


def _save_extracted_images(book_id: int,
                          page_num: int,
                          images: list):
    """
    Save extracted images to storage and create database records.
    
    Args:
        book_id: Book ID
        page_num: 1-based page number
        images: List of extracted image data objects
    """
    book = Book.objects.get(pk=book_id)
    image_extractor = ImageExtractor()
    
    for img_data in images:
        try:
            # Check if image already exists (deduplication)
            existing = ExtractedImage.objects.filter(
                book=book,
                page_number=page_num,
                xref=img_data.xref
            ).first()
            
            if existing:
                logger.debug(f"Image xref {img_data.xref} already exists, skipping")
                continue
            
            # Generate storage path
            upload_path = f'extracted_images/{book_id}/{page_num:04d}/'
            
            # Save to storage
            storage_path = image_extractor.save_to_storage(
                img_data,
                PrivateMediaStorage(),
                upload_path
            )
            
            # Create database record
            ExtractedImage.objects.create(
                book=book,
                page_number=page_num,
                xref=img_data.xref,
                image=storage_path,
                original_ext=img_data.ext,
                width=img_data.width,
                height=img_data.height,
                bbox_x0=img_data.bbox[0] if img_data.bbox else None,
                bbox_y0=img_data.bbox[1] if img_data.bbox else None,
                bbox_x1=img_data.bbox[2] if img_data.bbox else None,
                bbox_y1=img_data.bbox[3] if img_data.bbox else None,
                has_transparency=img_data.smask_xref > 0,
                colorspace=img_data.colorspace,
                file_size=len(img_data.image_bytes)
            )
            
            logger.debug(f"Saved image xref {img_data.xref} for book {book_id}")
            
        except Exception as e:
            logger.error(f"Failed to save image xref {img_data.xref}: {e}")
            # Continue with other images
            continue
