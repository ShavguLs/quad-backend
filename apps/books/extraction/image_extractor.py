"""PDF embedded image extraction using PyMuPDF.

Extracts images embedded in PDFs with:
- Original image data preservation (not page renders)
- Mask/transparency handling (smask)
- Metadata extraction (format, dimensions, position)
- Automatic format conversion to standard formats
"""

import io
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import pymupdf
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class ExtractedImage:
    """Metadata for an extracted image from PDF.
    
    Attributes:
        xref: PyMuPDF image reference number
        ext: Image format extension (png, jpeg, etc.)
        width: Image width in pixels
        height: Image height in pixels
        image_bytes: Raw image data
        colorspace: Colorspace integer code
        bbox: Position on page (x0, y0, x1, y1) or None
        page_number: Page where image appears (1-based)
        smask_xref: Mask reference if image has transparency
        pil_image: PIL Image object (created on demand)
    """
    xref: int
    ext: str
    width: int
    height: int
    image_bytes: bytes
    colorspace: int = 0
    bbox: Optional[Tuple[float, float, float, float]] = None
    page_number: int = 0
    smask_xref: int = 0
    _pil_image: Optional[Image.Image] = field(default=None, repr=False)
    
    @property
    def pil_image(self) -> Optional[Image.Image]:
        """Lazy-load PIL Image from bytes."""
        if self._pil_image is None and self.image_bytes:
            try:
                self._pil_image = Image.open(io.BytesIO(self.image_bytes))
            except Exception as e:
                logger.warning(f"Failed to load PIL image for xref {self.xref}: {e}")
        return self._pil_image
    
    @property
    def content_type(self) -> str:
        """Get HTTP content type for image format."""
        ext_to_mime = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "tiff": "image/tiff",
            "tif": "image/tiff",
        }
        return ext_to_mime.get(self.ext.lower(), "application/octet-stream")
    
    @property
    def filename(self) -> str:
        """Generate filename for extracted image."""
        return f"image_{self.page_number:04d}_{self.xref:04d}.{self.ext}"


class ImageExtractor:
    """Extract embedded images from PDF documents."""
    
    def __init__(self, max_image_size: int = 50 * 1024 * 1024):
        """
        Initialize image extractor.
        
        Args:
            max_image_size: Maximum image size in bytes (default 50MB)
        """
        self.max_image_size = max_image_size
        self.logger = logging.getLogger(__name__)
    
    def extract_from_page(self, doc: pymupdf.Document, 
                         page_num: int) -> List[ExtractedImage]:
        """
        Extract all embedded images from a single page.
        
        Args:
            doc: PyMuPDF document object
            page_num: 0-based page number
            
        Returns:
            List of ExtractedImage with metadata and raw bytes
        """
        page = doc[page_num]
        images = []
        
        # Get image references on this page
        try:
            image_list = page.get_images(full=True)
        except Exception as e:
            self.logger.warning(f"Failed to get images for page {page_num + 1}: {e}")
            return []
        
        for img_index, img in enumerate(image_list, start=1):
            xref = img[0]
            
            try:
                extracted = self._extract_single_image(
                    doc, page, xref, page_num + 1
                )
                if extracted:
                    images.append(extracted)
                    
            except Exception as e:
                self.logger.warning(
                    f"Failed to extract image {img_index} (xref={xref}) "
                    f"on page {page_num + 1}: {e}"
                )
                continue
        
        return images
    
    def _extract_single_image(self, doc: pymupdf.Document,
                             page: pymupdf.Page,
                             xref: int,
                             page_number: int) -> Optional[ExtractedImage]:
        """
        Extract a single image by xref with mask handling.
        
        Args:
            doc: PyMuPDF document
            page: PyMuPDF page containing the image
            xref: Image reference number
            page_number: 1-based page number
            
        Returns:
            ExtractedImage or None if extraction fails
        """
        # Extract base image data
        base_image = doc.extract_image(xref)
        
        if not base_image:
            self.logger.warning(f"No image data for xref {xref}")
            return None
        
        image_bytes = base_image["image"]
        ext = base_image["ext"]
        width = base_image["width"]
        height = base_image["height"]
        colorspace = base_image.get("colorspace", 0)
        
        # Check image size limit
        if len(image_bytes) > self.max_image_size:
            self.logger.warning(
                f"Image xref {xref} exceeds size limit "
                f"({len(image_bytes)} > {self.max_image_size})"
            )
            return None
        
        # Handle mask (transparency)
        smask_xref = base_image.get("smask", 0)
        if smask_xref > 0:
            try:
                image_bytes = self._apply_mask(doc, image_bytes, smask_xref, ext)
                # Update extension to png since we now have transparency
                ext = "png"
            except Exception as e:
                self.logger.warning(
                    f"Failed to apply mask for xref {xref}: {e}. "
                    f"Using image without transparency."
                )
        
        # Get bbox (position on page)
        bbox = self._get_image_bbox(page, xref)
        
        return ExtractedImage(
            xref=xref,
            ext=ext,
            width=width,
            height=height,
            image_bytes=image_bytes,
            colorspace=colorspace,
            bbox=bbox,
            page_number=page_number,
            smask_xref=smask_xref
        )
    
    def _apply_mask(self, doc: pymupdf.Document,
                   base_image_bytes: bytes,
                   smask_xref: int,
                   ext: str) -> bytes:
        """
        Apply transparency mask to image.
        
        Args:
            doc: PyMuPDF document
            base_image_bytes: Original image data
            smask_xref: Mask reference number
            ext: Image format extension
            
        Returns:
            Image bytes with transparency applied (PNG format)
        """
        try:
            # Load base image via PIL
            base = Image.open(io.BytesIO(base_image_bytes))
            
            # Convert to RGBA if not already
            if base.mode != 'RGBA':
                base = base.convert('RGBA')
            
            # Extract and apply mask
            mask_image = doc.extract_image(smask_xref)
            if mask_image:
                mask = Image.open(io.BytesIO(mask_image["image"]))
                
                # Resize mask to match base image if needed
                if mask.size != base.size:
                    mask = mask.resize(base.size, Image.Resampling.LANCZOS)
                
                # Convert mask to L mode if needed
                if mask.mode != 'L':
                    mask = mask.convert('L')
                
                # Apply mask as alpha channel
                base.putalpha(mask)
                
                # Save as PNG with transparency
                output = io.BytesIO()
                base.save(output, format='PNG', optimize=True)
                return output.getvalue()
            
        except Exception as e:
            self.logger.warning(f"Mask application failed: {e}")
        
        return base_image_bytes
    
    def _get_image_bbox(self, page: pymupdf.Page, 
                       xref: int) -> Optional[Tuple[float, float, float, float]]:
        """
        Get image position (bbox) on page.
        
        Args:
            page: PyMuPDF page
            xref: Image reference number
            
        Returns:
            Bounding box tuple (x0, y0, x1, y1) or None
        """
        try:
            # Find image in page's image list and get bbox
            image_list = page.get_images(full=True)
            for img in image_list:
                if img[0] == xref:
                    try:
                        bbox = page.get_image_bbox(img)
                        return (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
                    except Exception:
                        pass
        except Exception as e:
            self.logger.debug(f"Could not get bbox for xref {xref}: {e}")
        
        return None
    
    def extract_all(self, file_path: str) -> Dict[int, List[ExtractedImage]]:
        """
        Extract all images from entire PDF organized by page.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Dict mapping page number (1-based) to list of ExtractedImage
        """
        doc = pymupdf.open(file_path)
        all_images = {}
        
        try:
            for page_num in range(len(doc)):
                images = self.extract_from_page(doc, page_num)
                if images:
                    all_images[page_num + 1] = images
        finally:
            doc.close()
        
        return all_images
    
    def save_to_storage(self, image: ExtractedImage,
                       storage_backend,
                       upload_path: str) -> str:
        """
        Save extracted image to Django storage backend.
        
        Args:
            image: ExtractedImage to save
            storage_backend: Django storage instance
            upload_path: Base path for upload (e.g., 'extracted_images/')
            
        Returns:
            Storage path of saved file
        """
        from django.core.files.base import ContentFile
        
        filename = image.filename
        full_path = f"{upload_path}{filename}"
        
        try:
            storage_backend.save(full_path, 
                                ContentFile(image.image_bytes, name=filename))
            return full_path
        except Exception as e:
            self.logger.error(f"Failed to save image {filename}: {e}")
            raise


def extract_images_from_page(doc: pymupdf.Document, 
                             page_num: int) -> List[ExtractedImage]:
    """
    Convenience function to extract images from a single page.
    
    Args:
        doc: PyMuPDF document object
        page_num: 0-based page number
        
    Returns:
        List of ExtractedImage
    """
    extractor = ImageExtractor()
    return extractor.extract_from_page(doc, page_num)


def extract_image_with_mask(doc: pymupdf.Document, 
                           xref: int) -> Optional[bytes]:
    """
    Extract single image with mask applied.
    
    Args:
        doc: PyMuPDF document
        xref: Image reference number
        
    Returns:
        Image bytes with transparency or None
    """
    base_image = doc.extract_image(xref)
    
    if not base_image:
        return None
    
    image_bytes = base_image["image"]
    smask_xref = base_image.get("smask", 0)
    ext = base_image["ext"]
    
    if smask_xref > 0:
        extractor = ImageExtractor()
        try:
            return extractor._apply_mask(doc, image_bytes, smask_xref, ext)
        except Exception:
            pass
    
    return image_bytes
