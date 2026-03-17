#!/usr/bin/env python
"""
Standalone Playwright image generator script.

Usage:
    python generate_images.py <input_json_file> <output_json_file>

Input JSON format:
    [{"page_number": 1, "content": "<html>..."}, ...]

Output JSON format:
    {"status": "success", "results": [{"page_number": 1, "temp_path": "/path/to/file.png"}, ...]}
    or
    {"status": "error", "error": "error message"}
"""

#!/usr/bin/env python
"""
Standalone Playwright image generator script.

Usage:
    python generate_images.py <input_json_file> <output_json_file>

Input JSON format:
    [{"page_number": 1, "content": "<html>..."}, ...]

Output JSON format:
    {"status": "success", "results": [{"page_number": 1, "temp_path": "/path/to/file.png"}, ...]}
    or
    {"status": "error", "error": "error message"}
"""

import json
import logging
import os
import sys
import tempfile

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Set up Django BEFORE importing Django models
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

# Add api directory to path
api_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

logger.info("Setting up Django")

import django
django.setup()

from apps.books.publish.image_generator import PageImageGenerator


def main():
    logger.info("main() started")
    
    if len(sys.argv) != 3:
        logger.error("Usage: python generate_images.py <input_json_file> <output_json_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    logger.info(f"Starting image generation: input={input_file}, output={output_file}")
    
    try:
        # Read input
        with open(input_file, 'r') as f:
            pages_data = json.load(f)
        
        logger.info(f"Generating images for {len(pages_data)} pages")
        
        # Generate images
        results = []
        with PageImageGenerator() as generator:
            logger.info("PageImageGenerator initialized")
            for i, page_data in enumerate(pages_data):
                logger.info(f"Generating image for page {page_data['page_number']} ({i+1}/{len(pages_data)})")
                image_bytes = generator.generate_page_image(page_data['content'])
                
                # Write to temp file
                fd, temp_path = tempfile.mkstemp(suffix='.png')
                try:
                    os.write(fd, image_bytes)
                finally:
                    os.close(fd)
                
                results.append({
                    'page_number': page_data['page_number'],
                    'temp_path': temp_path,
                })
                logger.info(f"Generated image for page {page_data['page_number']}: {temp_path}")
        
        # Write output
        output = {'status': 'success', 'results': results}
        with open(output_file, 'w') as f:
            json.dump(output, f)
        
        logger.info(f"Successfully generated {len(results)} images")
        sys.exit(0)
        
    except Exception as e:
        import traceback
        logger.error(f"Error generating images: {e}")
        logger.error(traceback.format_exc())
        output = {
            'status': 'error',
            'error': f"{str(e)}\n{traceback.format_exc()}"
        }
        with open(output_file, 'w') as f:
            json.dump(output, f)
        sys.exit(1)


if __name__ == '__main__':
    main()
