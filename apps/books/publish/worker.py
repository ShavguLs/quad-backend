"""
Standalone Playwright worker - no Django imports at module level.

This module is designed to be imported by multiprocessing subprocesses
without triggering Django model imports.
"""


def _generate_images_worker(pages_data, result_queue):
    """
    Worker function that runs in a separate process.
    
    This function does ALL imports inside the function body to avoid
    Django model imports at module load time.
    """
    try:
        import os
        import sys
        import tempfile
        
        # Set Django settings module BEFORE any Django imports
        os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
        
        # Add the api directory to Python path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up from: apps/books/publish/worker.py to api/
        api_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        if api_dir not in sys.path:
            sys.path.insert(0, api_dir)
        
        # Setup Django
        import django
        django.setup()
        
        # Now safe to import Django-dependent modules
        from apps.books.publish.image_generator import PageImageGenerator
        
        results = []
        with PageImageGenerator() as generator:
            for page_data in pages_data:
                # Generate image
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
        
        result_queue.put(('success', results))
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        result_queue.put(('error', error_msg))
