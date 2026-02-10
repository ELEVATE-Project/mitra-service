import os
import logging
from chatbot.utils.S3.s3_service import upload_file_to_s3
from chatbot.utils.gotenberg_utils import generate_pdf_with_gotenberg
from chatbot.models.enums import MediaTypeChoices

logger = logging.getLogger('django')


def create_pdf_from_text(text_content: str) -> bytes:
    """
    Create a PDF file from text content using Gotenberg HTML-to-PDF service.
    """
    try:
        # Convert text to formatted HTML
        html_content = text_to_html(text_content)
        
        # Use Gotenberg to convert HTML to PDF
        pdf_content = generate_pdf_with_gotenberg(html_content)
        
        if not pdf_content:
            raise Exception("Gotenberg failed to generate PDF")
        
        logger.info(f"Successfully created PDF with {len(text_content)} characters")
        
        return pdf_content
        
    except Exception as e:
        logger.error(f"Error creating PDF from text: {e}", exc_info=True)
        raise


def text_to_html(text_content: str) -> str:
    """
    Convert plain text to formatted HTML for PDF generation.
    """
    # Escape HTML special characters
    import html
    escaped_text = html.escape(text_content)
    
    # Convert line breaks to <br> tags and paragraphs to <p> tags
    paragraphs = escaped_text.split('\n\n')
    formatted_paragraphs = []
    
    for para in paragraphs:
        if para.strip():
            # Replace single newlines with <br>
            formatted_para = para.replace('\n', '<br>')
            formatted_paragraphs.append(f'<p>{formatted_para}</p>')
    
    html_body = '\n'.join(formatted_paragraphs)
    
    # Create full HTML document with styling
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                font-size: 11pt;
                line-height: 1.6;
                margin: 2cm;
                color: #333;
            }}
            p {{
                margin-bottom: 1em;
                text-align: justify;
            }}
            h1, h2, h3 {{
                color: #2c3e50;
                margin-top: 1.5em;
                margin-bottom: 0.5em;
            }}
        </style>
    </head>
    <body>
        {html_body}
    </body>
    </html>
    """
    
    return html_template


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename and ensure it has .pdf extension.
    """
    try:
        # Remove any path separators
        filename = os.path.basename(filename)
        
        # Remove extension if present
        name_without_ext = os.path.splitext(filename)[0]
        
        # Replace any invalid characters
        safe_name = "".join(c for c in name_without_ext if c.isalnum() or c in (' ', '-', '_'))
        
        # Remove extra spaces and replace with underscores
        safe_name = '_'.join(safe_name.split())
        
        # Ensure it's not empty
        if not safe_name:
            safe_name = "download"
        
        # Add .pdf extension
        return f"{safe_name}.pdf"
        
    except Exception as e:
        logger.error(f"Error sanitizing filename: {e}")
        return "download.pdf"


def create_and_upload_file(
    *,
    content: str,
    filename: str,
    company_bot_id: int,
    session_id: str
) -> dict:
    """
    Create a PDF file from content and upload it to S3.
    """
    try:
        logger.info(f"Creating file for session {session_id}, company_bot {company_bot_id}")
        logger.info(f"Original filename: {filename}, content length: {len(content)} chars")
        
        # Sanitize filename and ensure .pdf extension
        safe_filename = sanitize_filename(filename)
        logger.info(f"Sanitized filename: {safe_filename}")
        
        # Create PDF from content using Gotenberg
        pdf_content = create_pdf_from_text(content)
        
        logger.info(f"PDF created successfully, size: {len(pdf_content)} bytes")
        
        # Prepare folder structure: chatbot/<company_bot_id>/
        folder_structure = f"chatbot/{company_bot_id}/"
        
        # Upload to S3
        s3_key = upload_file_to_s3(
            file_name=safe_filename,
            file_content=pdf_content,
            content_type=MediaTypeChoices.PDF,
            project_id=None,
            folder_structure=folder_structure
        )
        
        if not s3_key:
            logger.error("Failed to upload file to S3")
            return {
                'success': False,
                'error': 'Failed to upload file to S3'
            }
        
        # Construct media URL
        base = os.getenv("S3_MEDIA_URL")
        media_url = f"{base}{s3_key}"
        
        logger.info(f"File uploaded successfully: {media_url}")
        
        return {
            'success': True,
            'media_url': media_url,
            'file_name': safe_filename,
            's3_key': s3_key
        }
        
    except Exception as e:
        logger.error(f"Error creating and uploading file: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }
