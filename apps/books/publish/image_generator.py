"""
HTML-to-Image generator using Playwright.

This module provides page image generation from HTML content using
a headless browser for accurate rendering of styled content.

Requirements:
    pip install playwright
    playwright install chromium

Note:
    If Playwright is not available, the generator will raise a clear
    error indicating the missing dependency.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

# Attempt to import Playwright
try:
    from playwright.sync_api import sync_playwright
    from playwright._impl._driver import compute_driver_executable
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None  # type: ignore
    compute_driver_executable = None

import subprocess
import os

# Thread pool for running sync Playwright in async contexts
_executor = ThreadPoolExecutor(max_workers=4)


class PageImageGenerator:
    """
    Generate page images from HTML content using headless browser.
    
    This class uses Playwright with Chromium to render HTML content
    to PNG images. It supports context manager pattern for proper
    resource cleanup.
    
    Usage:
        with PageImageGenerator() as generator:
            image_bytes = generator.generate_page_image(html_content)
    
    Attributes:
        width: Viewport width in pixels (default 1200)
        height: Viewport height in pixels (default 1600)
    """
    
    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 1600
    
    def __init__(self, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT):
        """
        Initialize the image generator.
        
        Args:
            width: Viewport width in pixels
            height: Viewport height in pixels
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is required for image generation. "
                "Install with: pip install playwright \u0026\u0026 playwright install chromium"
            )
        
        self.width = width
        self.height = height
        self._playwright = None
        self._browser = None
    
    def _ensure_browsers_installed(self):
        """Install Playwright browsers if not already present."""
        try:
            # Try to launch - if it fails, install browsers
            test_playwright = sync_playwright().start()
            try:
                test_browser = test_playwright.chromium.launch()
                test_browser.close()
                test_playwright.stop()
                logger.info("Playwright browsers already installed")
                return True
            except Exception:
                test_playwright.stop()
                raise
        except Exception:
            logger.info("Playwright browsers not found, installing...")
            try:
                # Install chromium browser
                result = subprocess.run(
                    ["playwright", "install", "chromium"],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    logger.info("Playwright browsers installed successfully")
                    return True
                else:
                    logger.error(f"Failed to install browsers: {result.stderr}")
                    return False
            except Exception as e:
                logger.error(f"Error installing browsers: {e}")
                return False
    
    def __enter__(self):
        """Start Playwright and launch browser."""
        if not sync_playwright:
            raise RuntimeError("Playwright not available")
        
        # Ensure browsers are installed (for Heroku runtime)
        self._ensure_browsers_installed()
        
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        logger.debug("PageImageGenerator: Browser launched")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up browser and Playwright resources."""
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        logger.debug("PageImageGenerator: Resources cleaned up")
    
    def generate_page_image(
        self,
        html_content: str,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> bytes:
        """
        Render HTML content to PNG image bytes.
        
        Args:
            html_content: HTML content to render (body content only)
            width: Optional override for viewport width
            height: Optional override for viewport height
        
        Returns:
            PNG image bytes
        
        Raises:
            RuntimeError: If browser not started (use context manager)
        """
        if not self._browser:
            raise RuntimeError(
                "Browser not started. Use 'with PageImageGenerator() as generator:'"
            )
        
        viewport_width = width or self.width
        viewport_height = height or self.height
        
        page = self._browser.new_page(
            viewport={'width': viewport_width, 'height': viewport_height}
        )
        
        try:
            # Wrap content in proper HTML document with reader styling
            full_html = self._wrap_html(html_content)
            
            page.set_content(full_html)
            # Wait for fonts and layout to settle
            page.wait_for_load_state('networkidle')
            
            screenshot = page.screenshot(type='png', full_page=True)
            return screenshot
            
        finally:
            page.close()
    
    async def agenerate_page_image(
        self,
        html_content: str,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> bytes:
        """
        Async version of generate_page_image for use in async contexts.
        
        This method runs the synchronous Playwright code in a thread pool
        to avoid 'You cannot call this from an async context' errors.
        
        Args:
            html_content: HTML content to render (body content only)
            width: Optional override for viewport width
            height: Optional override for viewport height
        
        Returns:
            PNG image bytes
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor,
            self.generate_page_image,
            html_content,
            width,
            height
        )
    
    def _wrap_html(self, content: str) -> str:
        """
        Wrap HTML content in a complete document with styling.
        
        Args:
            content: HTML body content
        
        Returns:
            Complete HTML document string
        """
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            margin: 0;
            padding: 40px;
            font-family: Georgia, serif;
            font-size: 16px;
            line-height: 1.6;
            color: #333;
            background: white;
        }}
        p {{
            margin: 0 0 1em 0;
        }}
        h1, h2, h3, h4, h5, h6 {{
            font-family: Georgia, serif;
            margin: 0 0 0.5em 0;
            line-height: 1.2;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
    </style>
</head>
<body>{content}</body>
</html>"""
