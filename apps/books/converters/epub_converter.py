"""EPUB to text content converter using PyMuPDF."""

import logging
from typing import List

import pymupdf

from apps.books.models import Book
from .base import BaseConverter, ConversionError

logger = logging.getLogger(__name__)


class EPUBConverter(BaseConverter):
    """Convert EPUB files to content data using PyMuPDF."""
    
    DPI = 150  # Target DPI for good readability
    FORMAT = "png"  # PNG for lossless quality
    
    def supports(self, mime_type: str) -> bool:
        """Check if this converter supports the MIME type."""
        return mime_type in [
            'application/epub+zip',
            'application/epub',
        ]
    
    def convert(self, file_obj, book: Book) -> List[dict]:
        """
        Convert EPUB to content data for BookContent creation.
        
        PyMuPDF can open EPUB directly and converts it to PDF internally.
        We then process the content to generate data for BookContent.
        
        Args:
            file_obj: File-like object or bytes
            book: Book instance
            
        Returns:
            List of dicts with page content data:
            {
                'page_number': int,
                'html_content': str,
                'text_content': str,
                'image_data': bytes (optional),
            }
            
        Raises:
            ConversionError: If EPUB is corrupted or conversion fails
        """
        
        try:
            # Read file content
            if hasattr(file_obj, 'read'):
                content = file_obj.read()
            else:
                content = file_obj
            
            # Open EPUB document
            try:
                doc = pymupdf.open(stream=content, filetype="epub")
            except Exception as e:
                logger.error(f"Failed to open EPUB: {e}")
                raise ConversionError(f"Invalid or corrupted EPUB file: {e}")
            
            pages = []
            
            try:
                # Convert EPUB to PDF bytes
                try:
                    pdf_bytes = doc.convert_to_pdf()
                except Exception as e:
                    logger.error(f"Failed to convert EPUB to PDF: {e}")
                    raise ConversionError(f"Failed to process EPUB file: {e}")
                finally:
                    # Close EPUB document
                    doc.close()
                
                # Open the generated PDF
                try:
                    pdf_doc = pymupdf.open("pdf", pdf_bytes)
                except Exception as e:
                    logger.error(f"Failed to open converted PDF: {e}")
                    raise ConversionError(f"Failed to process EPUB content: {e}")
                
                try:
                    total_pages = len(pdf_doc)
                    logger.info(f"Converting EPUB with {total_pages} pages for book {book.id}")
                    
                    for page_num in range(total_pages):
                        try:
                            # Load page
                            page = pdf_doc.load_page(page_num)
                            
                            # Render at target DPI
                            pix = page.get_pixmap(dpi=self.DPI)
                            
                            # Convert to PNG bytes
                            img_data = pix.tobytes(self.FORMAT)
                            
                            # Extract text content
                            text_content = page.get_text("text") if page else ""
                            
                            # Create content data dict (no BookPage creation)
                            page_data = {
                                'page_number': page_num + 1,
                                'html_content': text_content,  # EPUB content is primarily text
                                'text_content': text_content,
                                'image_data': img_data,
                            }
                            pages.append(page_data)
                            
                            # Explicit cleanup
                            pix = None
                            page = None
                            
                        except Exception as e:
                            logger.error(f"Failed to convert page {page_num + 1}: {e}")
                            raise ConversionError(
                                f"Failed to convert page {page_num + 1}: {e}"
                            )
                    
                    logger.info(f"Successfully converted {len(pages)} pages for book {book.id}")
                    
                finally:
                    # Close PDF document
                    pdf_doc.close()
                    
            except ConversionError:
                raise
            except Exception as e:
                logger.error(f"Unexpected error during EPUB conversion: {e}")
                raise ConversionError(f"EPUB conversion failed: {e}")
                
        except ConversionError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during EPUB conversion: {e}")
            raise ConversionError(f"EPUB conversion failed: {e}")
        
        return pages
