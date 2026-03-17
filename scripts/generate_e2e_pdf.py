"""Generate sample-styled-book.pdf for E2E testing."""
import os
import sys

# Add the api directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


def generate_sample_pdf():
    """Generate a sample PDF with styled content for E2E testing."""
    output_path = os.path.join(
        os.path.dirname(__file__),
        '..', 'apps', 'books', 'fixtures', 'e2e', 'sample-styled-book.pdf'
    )
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18
    )
    
    styles = getSampleStyleSheet()
    story = []
    
    # H1: Title (centered, large)
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#000000'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    story.append(Paragraph("Sample Styled Book", title_style))
    story.append(Spacer(1, 20))
    
    # H2: Chapter 1 (bold, medium)
    chapter_style = ParagraphStyle(
        'Chapter',
        parent=styles['Heading2'],
        fontSize=18,
        textColor=HexColor('#333333'),
        spaceAfter=12
    )
    story.append(Paragraph("Chapter 1: Introduction", chapter_style))
    story.append(Spacer(1, 12))
    
    # Styled paragraph (colored text - red)
    colored_style_red = ParagraphStyle(
        'ColoredRed',
        parent=styles['Normal'],
        fontSize=12,
        textColor=HexColor('#FF0000')
    )
    story.append(Paragraph(
        "This paragraph has red text for color extraction testing.",
        colored_style_red
    ))
    story.append(Spacer(1, 12))
    
    # Centered paragraph
    centered_style = ParagraphStyle(
        'Centered',
        parent=styles['Normal'],
        fontSize=12,
        alignment=TA_CENTER
    )
    story.append(Paragraph(
        "This paragraph is centered for alignment testing.",
        centered_style
    ))
    story.append(Spacer(1, 12))
    
    # Right-aligned paragraph with blue color
    right_blue_style = ParagraphStyle(
        'RightBlue',
        parent=styles['Normal'],
        fontSize=12,
        textColor=HexColor('#0000FF'),
        alignment=TA_RIGHT
    )
    story.append(Paragraph(
        "This paragraph is right-aligned and blue.",
        right_blue_style
    ))
    story.append(Spacer(1, 20))
    
    # H2: Chapter 2
    story.append(Paragraph("Chapter 2: Content", chapter_style))
    story.append(Spacer(1, 12))
    
    # Normal paragraph with Georgia-like font
    normal_style = ParagraphStyle(
        'NormalCustom',
        parent=styles['Normal'],
        fontSize=11,
        fontName='Times-Roman',
        alignment=TA_LEFT
    )
    story.append(Paragraph(
        "This is a standard paragraph with left alignment. "
        "It contains multiple sentences to demonstrate normal text flow. "
        "The content should be extracted with proper formatting preserved.",
        normal_style
    ))
    story.append(Spacer(1, 12))
    
    # Another colored paragraph
    story.append(Paragraph(
        "Another red paragraph for color consistency testing.",
        colored_style_red
    ))
    story.append(Spacer(1, 12))
    
    # H3: Section (smaller heading)
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading3'],
        fontSize=14,
        textColor=HexColor('#444444'),
        spaceAfter=10
    )
    story.append(Paragraph("Section 2.1: Details", section_style))
    story.append(Spacer(1, 8))
    
    # Final paragraph
    story.append(Paragraph(
        "This concludes the sample book content for E2E testing. "
        "The PDF includes headings, styled text, and various alignments.",
        normal_style
    ))
    
    doc.build(story)
    
    # Get file size
    file_size = os.path.getsize(output_path)
    print(f"Generated: {output_path}")
    print(f"File size: {file_size} bytes ({file_size / 1024:.1f} KB)")
    
    return output_path


if __name__ == '__main__':
    try:
        output = generate_sample_pdf()
        print(f"\n✓ PDF generated successfully at: {output}")
    except Exception as e:
        print(f"\n✗ Failed to generate PDF: {e}")
        sys.exit(1)
