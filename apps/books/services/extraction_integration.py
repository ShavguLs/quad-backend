"""Extraction integration service to convert Phase 35 extraction results to BookContent.

Bridges the extraction pipeline (Phase 35) with the content storage model (Phase 36)
by converting ExtractedPage/ExtractedBlock data to BookContent blocks and linking
ExtractedImage records.
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from django.db import transaction

from apps.books.models import Book, BookContent, ContentVersion, ExtractedImage
from apps.books.models.content_blocks import (
    BlockType,
    BlockPosition,
    BlockMetadata,
    BlockFormatting,
    ParagraphBlock,
    HeadingBlock,
    ImageBlock,
)
from apps.books.extraction.text_extractor import ExtractedPage, ExtractedBlock
from apps.books.extraction.engine import ExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class ContentCreationResult:
    """Result of content creation from extraction."""
    content_pages: List[BookContent]
    pages_created: int
    images_linked: int
    errors: List[str]


class ExtractionToContentService:
    """Service to convert Phase 35 extraction results to BookContent records.
    
    This service bridges the extraction pipeline with the content storage model
    by converting ExtractedPage/ExtractedBlock data to BookContent blocks.
    """
    
    @staticmethod
    @transaction.atomic
    def create_content_from_extraction(
        book: Book,
        extraction_result: ExtractionResult,
        user=None
    ) -> List[BookContent]:
        """Create BookContent records from extraction result.
        
        Converts each ExtractedPage to a BookContent record with properly
        structured blocks. Calculates character offsets for search/selection.
        Creates initial ContentVersion for each page.
        
        Args:
            book: Book instance to create content for
            extraction_result: ExtractionResult from Phase 35 extraction
            user: Optional user creating the content (for version tracking)
            
        Returns:
            List of created BookContent instances
        """
        content_pages = []
        
        for extracted_page in extraction_result.pages:
            # Convert blocks and calculate character positions
            blocks = []
            current_offset = 0
            
            for extracted_block in extracted_page.blocks:
                # Convert extracted block to content block
                content_block = ExtractionToContentService._convert_block(
                    extracted_block,
                    current_offset
                )
                blocks.append(content_block.to_dict())
                
                # Update offset for next block (+1 for separator)
                text_length = len(content_block.text) if hasattr(content_block, 'text') else 0
                current_offset += text_length + 1
            
            # Create BookContent record
            content = BookContent.objects.create(
                book=book,
                page_number=extracted_page.page_number,
                blocks=blocks,
                version=1
            )
            
            # Create initial ContentVersion
            ContentVersion.create_version(
                book_content_id=content.id,
                blocks=blocks,
                version_type='auto',
                user=user,
                change_summary="Initial content from PDF extraction"
            )
            
            content_pages.append(content)
            logger.debug(
                f"Created BookContent for book {book.id} page {extracted_page.page_number} "
                f"with {len(blocks)} blocks"
            )
        
        # Update book extraction status if not already completed
        if book.extraction_status != 'completed':
            book.extraction_status = 'completed'
            book.save(update_fields=['extraction_status', 'updated_at'])
        
        logger.info(
            f"Created {len(content_pages)} BookContent records for book {book.id}"
        )
        
        return content_pages
    
    @staticmethod
    def _convert_block(extracted_block: ExtractedBlock, start_offset: int) -> Any:
        """Convert ExtractedBlock to appropriate ContentBlock type.
        
        Args:
            extracted_block: Block from text extraction
            start_offset: Character offset where this block starts
            
        Returns:
            ContentBlock instance (ParagraphBlock or HeadingBlock)
        """
        # Generate unique block ID based on position
        block_id = f"blk_{extracted_block.x0:.0f}_{extracted_block.y0:.0f}"
        
        # Extract text from lines
        text = " ".join(line.text for line in extracted_block.lines)
        
        # Calculate character positions
        end_offset = start_offset + len(text)
        
        position = BlockPosition(
            start=start_offset,
            end=end_offset,
            page_x=extracted_block.x0,
            page_y=extracted_block.y0
        )
        
        metadata = BlockMetadata(
            source="extraction",
            confidence=0.9  # Default confidence
        )
        
        # Determine block type and create appropriate block
        if extracted_block.block_type == "heading":
            # Aggregate formatting from lines
            sizes = [line.size for line in extracted_block.lines if line.size > 0]
            font_size = max(sizes) if sizes else 12.0
            
            formatting = BlockFormatting(
                bold=any(line.is_bold for line in extracted_block.lines),
                italic=any(line.is_italic for line in extracted_block.lines),
                font_size=font_size,
                font_family=extracted_block.lines[0].font_name if extracted_block.lines else None,
                color=extracted_block.lines[0].color if extracted_block.lines else None,
                alignment=extracted_block.alignment if extracted_block.alignment in {"left", "center", "right", "justify"} else "left",
            )
            
            return HeadingBlock(
                id=block_id,
                type=BlockType.HEADING,
                level=extracted_block.heading_level or 1,
                text=text,
                position=position,
                formatting=formatting,
                metadata=metadata
            )
        else:
            # Paragraph block
            sizes = [line.size for line in extracted_block.lines if line.size > 0]
            font_size = sum(sizes) / len(sizes) if sizes else 12.0
            
            formatting = BlockFormatting(
                bold=any(line.is_bold for line in extracted_block.lines),
                italic=any(line.is_italic for line in extracted_block.lines),
                font_size=font_size,
                font_family=extracted_block.lines[0].font_name if extracted_block.lines else None,
                color=extracted_block.lines[0].color if extracted_block.lines else None,
                alignment=extracted_block.alignment if extracted_block.alignment in {"left", "center", "right", "justify"} else "left",
            )
            
            return ParagraphBlock(
                id=block_id,
                type=BlockType.PARAGRAPH,
                text=text,
                position=position,
                formatting=formatting,
                metadata=metadata
            )
    
    @staticmethod
    def link_extracted_images(
        book: Book,
        extraction_result: ExtractionResult
    ) -> int:
        """Link ExtractedImage records to ImageBlock references in content.
        
        Finds image blocks in BookContent that have xref values and links them
to the corresponding ExtractedImage records by matching (book, page_number, xref).
        
        Args:
            book: Book instance
            extraction_result: ExtractionResult containing page information
            
        Returns:
            Number of images successfully linked
        """
        linked_count = 0
        
        for extracted_page in extraction_result.pages:
            page_number = extracted_page.page_number
            
            try:
                # Get BookContent for this page
                content = BookContent.objects.get(
                    book=book,
                    page_number=page_number
                )
                
                # Find image blocks with xref
                updated = False
                blocks = content.blocks
                
                for block in blocks:
                    if block.get('type') != 'image':
                        continue
                    
                    xref = block.get('xref')
                    if not xref:
                        continue
                    
                    # Try to find matching ExtractedImage
                    try:
                        image = ExtractedImage.objects.get(
                            book=book,
                            page_number=page_number,
                            xref=xref
                        )
                        
                        # Update block with image reference
                        block['image_id'] = str(image.id)
                        
                        # Update metadata
                        metadata = block.get('metadata', {})
                        metadata['extracted_image_id'] = image.id
                        metadata['width'] = image.width
                        metadata['height'] = image.height
                        block['metadata'] = metadata
                        
                        updated = True
                        linked_count += 1
                        
                        logger.debug(
                            f"Linked image xref {xref} to ExtractedImage {image.id} "
                            f"for book {book.id} page {page_number}"
                        )
                        
                    except ExtractedImage.DoesNotExist:
                        logger.warning(
                            f"No ExtractedImage found for book {book.id} "
                            f"page {page_number} xref {xref}"
                        )
                        continue
                
                # Save updated blocks if any images were linked
                if updated:
                    content.save(update_fields=['blocks'])
                    
            except BookContent.DoesNotExist:
                logger.warning(
                    f"No BookContent found for book {book.id} page {page_number}"
                )
                continue
            except Exception as e:
                logger.error(
                    f"Error linking images for book {book.id} page {page_number}: {e}"
                )
                continue
        
        logger.info(
            f"Linked {linked_count} images to content blocks for book {book.id}"
        )
        
        return linked_count
    
    @staticmethod
    def create_content_from_pages(
        book: Book,
        pages: List[ExtractedPage],
        user=None
    ) -> List[BookContent]:
        """Create BookContent records from a list of ExtractedPages.
        
        Convenience method for when you have pages list directly instead of
        full ExtractionResult.
        
        Args:
            book: Book instance
            pages: List of ExtractedPage from extraction
            user: Optional user creating the content
            
        Returns:
            List of created BookContent instances
        """
        # Create minimal ExtractionResult wrapper
        extraction_result = ExtractionResult(
            book_id=book.id,
            pages=pages,
            total_pages=len(pages)
        )
        
        return ExtractionToContentService.create_content_from_extraction(
            book=book,
            extraction_result=extraction_result,
            user=user
        )
