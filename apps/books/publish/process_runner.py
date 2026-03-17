"""
Process-based Playwright runner using subprocess.

This avoids multiprocessing pickle/import issues by using subprocess.run
directly with a standalone script.
"""

import json
import logging
import os
import subprocess
import tempfile
from typing import List, Tuple

logger = logging.getLogger(__name__)


def generate_page_images_in_process(pages_data: List[dict]) -> Tuple[str, List[dict]]:
    """
    Generate page images using Playwright in a completely separate process.
    
    Uses subprocess.run to execute a standalone script, avoiding all
    multiprocessing pickle and import issues.
    
    Args:
        pages_data: List of dicts with 'page_number' and 'content'
    
    Returns:
        Tuple of (status, results) where status is 'success' or 'error'
    """
    logger.info(f"Starting image generation for {len(pages_data)} pages")
    
    # Create temp files for input/output
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f_in:
        json.dump(pages_data, f_in)
        input_file = f_in.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f_out:
        output_file = f_out.name
    
    logger.info(f"Input file: {input_file}, Output file: {output_file}")
    
    try:
        # Find the generate_images.py script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, 'generate_images.py')
        
        logger.info(f"Running script: {script_path}")
        
        # Run the script
        logger.info(f"Starting subprocess: python {script_path}")
        result = subprocess.run(
            ['python', script_path, input_file, output_file],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        logger.info(f"Subprocess completed with return code: {result.returncode}")
        
        if result.stderr:
            logger.info(f"Subprocess stderr: {result.stderr}")
        
        # Read output
        if os.path.exists(output_file):
            with open(output_file, 'r') as f:
                output = json.load(f)
            
            if output.get('status') == 'success':
                logger.info(f"Successfully generated {len(output.get('results', []))} images")
                return ('success', output.get('results', []))
            else:
                logger.error(f"Error in subprocess output: {output.get('error', 'Unknown error')}")
                return ('error', [])
        else:
            logger.error(f"Output file not found: {output_file}")
            return ('error', [])
            
    except subprocess.TimeoutExpired:
        logger.error("Subprocess timed out after 5 minutes")
        return ('timeout', [])
    except Exception as e:
        logger.exception(f"Error running subprocess: {e}")
        return ('error', [])
    finally:
        # Clean up temp files
        try:
            if os.path.exists(input_file):
                os.unlink(input_file)
            if os.path.exists(output_file):
                os.unlink(output_file)
        except:
            pass
