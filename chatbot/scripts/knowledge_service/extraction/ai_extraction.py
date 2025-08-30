import json
from typing import Dict, List, Any, Set
from pathlib import Path
import PyPDF2
import docx
import pandas as pd
from jinja2 import Template
import json_repair
import requests
import tempfile
import os
import re
import base64
import io
import logging
from urllib.parse import urlparse
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import FileTypeChoices

# Set up logging
logger = logging.getLogger('django')
MAX_DEPTH = 1
# Additional imports for enhanced features
try:
    import fitz  # PyMuPDF for better PDF handling

    HAS_PYMUPDF = True
    logger.info("PyMuPDF available for enhanced PDF processing")
except ImportError:
    HAS_PYMUPDF = False
    logger.warning("PyMuPDF not available. Using PyPDF2 for text extraction only.")

try:
    from PIL import Image

    HAS_PIL = True
    logger.info("PIL available for image processing")
except ImportError:
    HAS_PIL = False
    logger.warning("PIL not available. Image processing will be limited.")

try:
    import pytesseract
    from PIL import Image as PILImage

    HAS_OCR = True
    logger.info("pytesseract available for OCR processing")
except ImportError:
    HAS_OCR = False
    logger.warning("pytesseract not available. Scanned document processing will be limited.")

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
    logger.info("pdfplumber available for enhanced PDF text extraction")
except ImportError:
    HAS_PDFPLUMBER = False
    logger.warning("pdfplumber not available. Using PyMuPDF/PyPDF2 fallback.")


class DocumentExtractor:
    """Extract structured content from documents using AWS Bedrock Llama model with enhanced features"""

    def __init__(self, max_depth: int = MAX_DEPTH, max_subdocs: int = 10,
                 enable_ocr: bool = True, compress_images: bool = True):
        """Initialize with enhanced features"""
        self.max_depth = max_depth
        self.max_subdocs = max_subdocs
        self.processed_urls: Set[str] = set()
        self.url_cache: Dict[str, str] = {}
        self.enable_ocr = enable_ocr and HAS_OCR
        self.compress_images = compress_images

        # File validation
        self.allowed_extensions = {'.pdf', '.doc', '.docx', '.txt', '.csv', '.xls', '.xlsx'}
        self.max_file_size_mb = 50
        self.max_file_size_bytes = self.max_file_size_mb * 1024 * 1024

    def extract_urls_from_text(self, text: str) -> List[str]:
        """Extract all URLs from text content with improved regex"""
        try:
            # Enhanced URL pattern to catch more formats
            url_patterns = [
                r'https?://(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*)?(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?',
                r'www\.(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*)?(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?'
            ]

            urls = []
            for pattern in url_patterns:
                found_urls = re.findall(pattern, text, re.IGNORECASE)
                urls.extend(found_urls)

            # Add https:// to www URLs
            processed_urls = []
            for url in urls:
                if url.startswith('www.'):
                    url = 'https://' + url
                processed_urls.append(url)

            # Remove duplicates while preserving order
            unique_urls = []
            seen = set()
            for url in processed_urls:
                if url not in seen and len(url) > 10:
                    unique_urls.append(url)
                    seen.add(url)

            logger.info(f"Extracted {len(unique_urls)} unique URLs")
            return unique_urls

        except Exception as e:
            logger.error(f"Error extracting URLs: {e}")
            return []

    def is_document_url(self, url: str, depth: int = 0) -> bool:
        """Check if URL points to a document - ONLY .pdf, .docx, .txt at all levels"""
        try:
            # Exclude non-document URLs at all levels
            excluded_patterns = [
                'googleusercontent.com', 'gstatic.com', 'chrome.google.com',
                'googleapis.com', '/favicon', '.ico', '.png', '.jpg', '.jpeg',
                '.gif', '.svg', 'forms.google.com', 'youtube.com', 'twitter.com'
            ]

            for pattern in excluded_patterns:
                if pattern in url.lower():
                    return False

            # Check for Google Docs/Drive with document formats
            if 'docs.google.com/document' in url:
                return True
            elif 'drive.google.com/file' in url:
                return True

            # Check standard URLs for specific extensions only
            parsed_url = urlparse(url)
            path = parsed_url.path.lower()

            # ONLY these extensions are allowed at ANY level
            allowed_extensions = ['.pdf', '.docx', '.txt']
            for ext in allowed_extensions:
                if path.endswith(ext):
                    return True

            return False
        except Exception as e:
            logger.error(f"Error checking if URL is document: {e}")
            return False

    def convert_google_drive_url(self, url: str) -> str:
        """Convert Google URLs to downloadable formats - only for document types"""
        try:
            if 'docs.google.com/document' in url:
                if '/d/' in url:
                    doc_id = url.split('/d/')[1].split('/')[0]
                    # return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
                    return f"https://docs.google.com/document/d/{doc_id}/export?format=docx"

            elif 'drive.google.com/file' in url:
                if '/d/' in url:
                    file_id = url.split('/d/')[1].split('/')[0]
                    return f"https://drive.google.com/uc?id={file_id}&export=download"

            if 'docs.google.com/spreadsheets' in url:
                return None

            return url
        except Exception as e:
            logger.error(f"Error converting Google Drive URL: {e}")
            return url

    def _image_to_base64(self, image_bytes: bytes, image_format: str = "PNG") -> str:
        """Convert image bytes to base64 string"""
        try:
            if HAS_PIL and self.compress_images:
                # Use PIL to potentially optimize/convert image
                image = Image.open(io.BytesIO(image_bytes))
                buffer = io.BytesIO()

                # Convert to RGB if necessary
                if image.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', image.size, (255, 255, 255))
                    background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                    image = background

                # Resize if too large
                max_dimension = 1024
                if max(image.size) > max_dimension:
                    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

                image.save(buffer, format="JPEG", quality=85, optimize=True)
                image_bytes = buffer.getvalue()

            # Encode to base64
            base64_string = base64.b64encode(image_bytes).decode('utf-8')
            mime_type = f"image/{image_format.lower()}"
            return f"data:{mime_type};base64,{base64_string}"

        except Exception as e:
            logger.error(f"Error converting image to base64: {e}")
            return ""

    def _extract_images_from_pdf_pymupdf(self, content_bytes: bytes) -> List[Dict[str, Any]]:
        """Extract images from PDF using PyMuPDF"""
        images = []
        if not HAS_PYMUPDF:
            return images

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(content_bytes)
                temp_file_path = temp_file.name

            try:
                doc = fitz.open(temp_file_path)

                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    image_list = page.get_images()

                    max_images_per_page = 10

                    for img_index, img in enumerate(image_list[:max_images_per_page]):
                        try:
                            xref = img[0]
                            pix = fitz.Pixmap(doc, xref)

                            # Skip very small images
                            if pix.width < 100 or pix.height < 100:
                                pix = None
                                continue

                            # Skip very large images
                            if pix.width * pix.height > 2048 * 2048:
                                pix = None
                                continue

                            # Convert to PNG bytes
                            if pix.n - pix.alpha < 4:  # GRAY or RGB
                                img_bytes = pix.tobytes("png")
                                base64_image = self._image_to_base64(img_bytes, "PNG")

                                if base64_image:
                                    images.append({
                                        "page": page_num + 1,
                                        "index": img_index,
                                        "width": pix.width,
                                        "height": pix.height,
                                        "base64": base64_image,
                                        "format": "png"
                                    })

                            pix = None

                        except Exception as e:
                            logger.error(f"Error extracting image {img_index} from page {page_num + 1}: {e}")

                    if len(images) > 50:
                        logger.warning("Reached maximum image limit (50)")
                        break

                doc.close()

            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

            logger.info(f"Extracted {len(images)} images from PDF")
            return images

        except Exception as e:
            logger.error(f"Error extracting images from PDF: {e}")
            return []

    def _extract_images_from_docx(self, content_bytes: bytes) -> List[Dict[str, Any]]:
        """Extract images from DOCX file"""
        images = []

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
                temp_file.write(content_bytes)
                temp_file_path = temp_file.name

            try:
                doc = docx.Document(temp_file_path)

                image_count = 0
                for rel in doc.part.rels.values():
                    if "image" in rel.target_ref:
                        try:
                            image_part = rel.target_part
                            image_bytes = image_part.blob

                            if len(image_bytes) < 1000:
                                continue

                            content_type = image_part.content_type
                            image_format = "PNG"
                            if "jpeg" in content_type or "jpg" in content_type:
                                image_format = "JPEG"

                            base64_image = self._image_to_base64(image_bytes, image_format)

                            if base64_image:
                                images.append({
                                    "index": image_count,
                                    "base64": base64_image,
                                    "format": image_format.lower()
                                })
                                image_count += 1

                        except Exception as e:
                            logger.error(f"Error extracting image from DOCX: {e}")

            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

            logger.info(f"Extracted {len(images)} images from DOCX")
            return images

        except Exception as e:
            logger.error(f"Error extracting images from DOCX: {e}")
            return []

    def _perform_ocr_on_pdf(self, content_bytes: bytes) -> str:
        """Perform OCR on scanned PDF pages"""
        if not self.enable_ocr or not HAS_PYMUPDF:
            return ""

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(content_bytes)
                temp_file_path = temp_file.name

            try:
                doc = fitz.open(temp_file_path)
                ocr_text_parts = []

                for page_num in range(min(10, len(doc))):
                    page = doc.load_page(page_num)

                    # Check if page has extractable text
                    page_text = page.get_text()
                    if len(page_text.strip()) > 50:
                        continue

                    # Convert page to image for OCR
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_data = pix.tobytes("png")

                    # Perform OCR
                    image = PILImage.open(io.BytesIO(img_data))
                    ocr_text = pytesseract.image_to_string(image, lang='eng')

                    if ocr_text.strip():
                        ocr_text_parts.append(f"[Page {page_num + 1} - OCR]\n{ocr_text}")

                    pix = None

                doc.close()
                return '\n\n'.join(ocr_text_parts)

            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            logger.error(f"Error performing OCR: {e}")
            return ""

    def _extract_pdf_text_enhanced(self, content_bytes: bytes) -> str:
        """Enhanced PDF text extraction with multiple methods"""
        text = ""

        # Try pdfplumber first if available
        if HAS_PDFPLUMBER:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    temp_file.write(content_bytes)
                    temp_file_path = temp_file.name

                try:
                    text_parts = []
                    import pdfplumber
                    with pdfplumber.open(temp_file_path) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text and page_text.strip():
                                text_parts.append(page_text)
                    text = '\n'.join(text_parts)
                finally:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)

                if text and len(text.strip()) > 50:
                    logger.info(f"pdfplumber extracted {len(text)} characters")
                    return text
            except Exception as e:
                logger.error(f"pdfplumber failed: {e}")

        # Try PyMuPDF next
        if HAS_PYMUPDF and not text:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    temp_file.write(content_bytes)
                    temp_file_path = temp_file.name

                try:
                    doc = fitz.open(temp_file_path)
                    text_parts = []
                    for page_num in range(len(doc)):
                        page = doc.load_page(page_num)
                        text_parts.append(page.get_text())
                    text = '\n'.join(text_parts)
                    doc.close()
                finally:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)

                if text and len(text.strip()) > 50:
                    logger.info(f"PyMuPDF extracted {len(text)} characters")
                    return text
            except Exception as e:
                logger.error(f"PyMuPDF failed: {e}")

        # Fallback to PyPDF2
        if not text:
            try:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(content_bytes))
                text_parts = []
                for page in pdf_reader.pages:
                    text_parts.append(page.extract_text())
                text = '\n'.join(text_parts)
                logger.info(f"PyPDF2 extracted {len(text)} characters")
            except Exception as e:
                logger.error(f"PyPDF2 failed: {e}")

        # Try OCR if text extraction failed
        if (not text or len(text.strip()) < 50) and self.enable_ocr:
            logger.info("Attempting OCR on potentially scanned document")
            ocr_text = self._perform_ocr_on_pdf(content_bytes)
            if ocr_text:
                text = text + "\n\n[OCR Content]\n" + ocr_text if text else ocr_text

        return text

    def extract_text_from_url(self, url: str) -> tuple[str, List[Dict[str, Any]], Any]:
        """Extract text content and images from document URL"""
        try:
            logger.info(f"Extracting from: {url}")

            # Check cache
            if url in self.url_cache:
                return self.url_cache[url], [], None

            # Convert Google Drive URLs to downloadable format
            download_url = self.convert_google_drive_url(url)
            if download_url is None:
                logger.info(f"Skipped non-document URL: {url}")
                return "", [], None
            if download_url != url:
                logger.info(f"Converted to: {download_url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(download_url, headers=headers, timeout=30)
            response.raise_for_status()

            text = ""
            images = []

            # Handle Google Docs text export directly
            if 'docs.google.com' in download_url and 'export?format=txt' in download_url:
                text = response.text
                logger.info(f"Extracted {len(text)} characters from Google Doc")
                self.url_cache[url] = text
                return text, images, None

            # Determine file type
            content_type = response.headers.get('content-type', '').lower()

            content_preview = response.content[:10] if response.content else b''
            is_pdf = content_preview.startswith(b'%PDF') or 'pdf' in content_type
            logger.info("content_type: ", content_type)
            if is_pdf:
                text = self._extract_pdf_text_enhanced(response.content)
                images = self._extract_images_from_pdf_pymupdf(response.content)
                media_type = FileTypeChoices.PDF
                logger.info("Assigned media type as : ", media_type)
            elif 'word' in content_type or 'document' in content_type:
                # Process DOCX
                with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                try:
                    doc = docx.Document(temp_file_path)
                    text_parts = []
                    for para in doc.paragraphs:
                        if para.text.strip():
                            text_parts.append(para.text)
                    text = '\n'.join(text_parts)
                finally:
                    media_type = FileTypeChoices.DOCX
                    logger.info("Assigned media type as : ", media_type)
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)

                images = self._extract_images_from_docx(response.content)
            else:
                # Try as plain text
                text = response.text
                media_type = FileTypeChoices.TXT
                logger.info("Assigned media type as : ", media_type)

            if text:
                self.url_cache[url] = text

            logger.info(
                f"For url: {url}, Extracted {len(text)} characters and {len(images)} "
                f"images and file type as {media_type}"
            )
            return text, images, media_type

        except Exception as e:
            logger.error(f"Failed to extract from URL {url}: {e}")
            return "", [], None

    def extract_text_from_file(self, file, file_extension: str) -> tuple[str, List[Dict[str, Any]]]:
        """Extract text content and images from various file types"""
        try:
            file_extension = file_extension.lower().strip('.')
            text = ""
            images = []

            # Handle file path vs file object
            if isinstance(file, (str, Path)):
                file_path = Path(file)
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found: {file_path}")

                if file_extension == 'pdf':
                    with open(file_path, 'rb') as f:
                        content_bytes = f.read()
                    text = self._extract_pdf_text_enhanced(content_bytes)
                    images = self._extract_images_from_pdf_pymupdf(content_bytes)
                elif file_extension in ['doc', 'docx']:
                    text = self._extract_docx_text(file_path)
                    with open(file_path, 'rb') as f:
                        images = self._extract_images_from_docx(f.read())
                elif file_extension == 'txt':
                    text = self._extract_txt_text(file_path)
                elif file_extension == 'csv':
                    text = self._extract_csv_text(file_path)
                elif file_extension in ['xls', 'xlsx']:
                    text = self._extract_excel_text(file_path)
            else:
                # Handle file object
                if file_extension == 'pdf':
                    file.seek(0)
                    content_bytes = file.read()
                    text = self._extract_pdf_text_enhanced(content_bytes)
                    images = self._extract_images_from_pdf_pymupdf(content_bytes)
                elif file_extension in ['doc', 'docx']:
                    file.seek(0)
                    content_bytes = file.read()
                    text = self._extract_docx_text_from_object(io.BytesIO(content_bytes))
                    images = self._extract_images_from_docx(content_bytes)
                elif file_extension == 'txt':
                    text = self._extract_txt_text_from_object(file)
                elif file_extension == 'csv':
                    text = self._extract_csv_text_from_object(file)
                elif file_extension in ['xls', 'xlsx']:
                    text = self._extract_excel_text_from_object(file)

            return text, images

        except Exception as e:
            logger.error(f"Error extracting from file: {e}")
            return "", []

    def _extract_pdf_text(self, file) -> str:
        """Extract text from PDF (fallback method)"""
        pdf_reader = PyPDF2.PdfReader(file)
        text_parts = []
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text_parts.append(page.extract_text())
        return '\n'.join(text_parts)

    def _extract_docx_text(self, file_path) -> str:
        """Extract text from Word document (file path)"""
        doc = docx.Document(file_path)
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)
        return '\n'.join(text_parts)

    def _extract_docx_text_from_object(self, file) -> str:
        """Extract text from Word document (file object)"""
        doc = docx.Document(file)
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)
        return '\n'.join(text_parts)

    def _extract_txt_text(self, file_path) -> str:
        """Extract text from plain text file (file path)"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    def _extract_txt_text_from_object(self, file) -> str:
        """Extract text from plain text file (file object)"""
        content = file.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
        return content

    def _extract_csv_text(self, file_path) -> str:
        """Extract text from CSV (file path)"""
        df = pd.read_csv(file_path)
        return df.to_string()

    def _extract_csv_text_from_object(self, file) -> str:
        """Extract text from CSV (file object)"""
        df = pd.read_csv(file)
        return df.to_string()

    def _extract_excel_text(self, file_path) -> str:
        """Extract text from Excel (file path)"""
        df = pd.read_excel(file_path)
        return df.to_string()

    def _extract_excel_text_from_object(self, file) -> str:
        """Extract text from Excel (file object)"""
        df = pd.read_excel(file)
        return df.to_string()

    def read_document(self, file_path: str) -> str:
        """Extract text content from various document formats"""
        file_path = Path(file_path)
        file_ext = file_path.suffix.lower().strip('.')

        try:
            text, _ = self.extract_text_from_file(file_path, file_ext)
            return text
        except Exception as e:
            raise Exception(f"Error reading document: {str(e)}")

    def _find_explicit_tag_sections(self, document_text: str) -> List[str]:
        """Find explicit tag/classification sections in the document"""
        try:
            tag_sections = []

            # Common patterns for explicit tag/classification sections
            tag_patterns = [
                r'(?:tags?|keywords?|categories|classification|subject areas?|topics?|themes?):\s*([^\n\r]+)',
                r'(?:^|\n)(?:tags?|keywords?|categories|classification|subject areas?|topics?|themes?):?\s*\n([^\n\r]+(?:\n[^\n\r]+)*?)(?=\n\n|\n[A-Z]|\n\s*$|$)',
                r'(?:^|\n)(?:tags?|keywords?|categories|classification|subject areas?|topics?|themes?):?\s*\n((?:\s*[-•*]\s*[^\n\r]+\n?)+)',
                r'(?:^|\n)(?:tags?|keywords?|categories|classification|subject areas?|topics?|themes?):?\s*\n((?:\s*\d+\.\s*[^\n\r]+\n?)+)',
            ]

            doc_lower = document_text.lower()

            for pattern in tag_patterns:
                matches = re.finditer(pattern, doc_lower, re.MULTILINE | re.IGNORECASE)
                for match in matches:
                    section_content = match.group(1).strip()
                    if section_content and len(section_content) > 2:
                        tag_sections.append(section_content)

            # Remove duplicates while preserving order
            unique_sections = []
            seen_content = set()
            for section in tag_sections:
                section_key = section.lower().strip()
                if section_key not in seen_content:
                    unique_sections.append(section)
                    seen_content.add(section_key)

            return unique_sections

        except Exception as e:
            logger.error(f"Error finding explicit tag sections: {e}")
            return []

    def _validate_and_enhance_result(self, result: Dict[str, Any], document_text: str) -> Dict[str, Any]:
        """Validate and enhance the extracted result"""
        # Ensure all required fields exist
        default_response = {
            "title": "",
            "organization": "",
            "tags": [],
            "exact_content": "",
            "summary": "",
            "document_type": "",
            "key_entities": [],
            "url": [],
            "subdocument": [],
            "images": []
        }

        for key in default_response:
            if key not in result:
                result[key] = default_response[key]

        # Ensure exact_content is preserved
        if not result.get('exact_content'):
            result['exact_content'] = document_text

        # Find explicit tag sections
        explicit_tag_sections = self._find_explicit_tag_sections(document_text)

        # Validate tags
        if result.get('tags'):
            validated_tags = []
            for tag in result['tags']:
                if isinstance(tag, str):
                    # Try to parse as JSON first
                    try:
                        parsed_tag = json_repair.repair_json(tag, return_objects=True)
                        if isinstance(parsed_tag, dict) and 'text' in parsed_tag:
                            # Successfully parsed as tag dict
                            validated_tags.append(parsed_tag)
                        else:
                            # Not a valid tag dict, treat as plain string
                            validated_tags.append({"text": tag, "source": "generated"})
                    except:
                        # Failed to parse as JSON, treat as plain string
                        validated_tags.append({"text": tag, "source": "generated"})
                elif isinstance(tag, dict) and 'text' in tag:
                    # Already a proper dict with text field
                    validated_tags.append(tag)
            result['tags'] = validated_tags
        # Ensure minimum content quality
        if not result.get('title') or len(result['title'].strip()) < 3:
            content_words = document_text.split()[:10]
            result['title'] = ' '.join(content_words).strip() + '...' if content_words else 'Untitled Document'

        return result

    def extract_basic_content(
            self, document_text, company_bot, extracted_images: List[Dict[str, Any]] = None, other_data=None
    ) -> Dict[str, Any]:
        """Extract basic content using Bedrock"""
        default_response = {
            "title": "",
            "organization": "",
            "tags": [],
            # "exact_content": document_text,  # Always preserve content
            "summary": "",
            "document_type": "",
            "key_entities": [],
            "url": [],
            "subdocument": [],
            "images": extracted_images or []
        }

        try:
            logger.info("Processing content with Bedrock...")

            # Preserve complete content
            complete_content = document_text

            system_prompt = [
                {
                    'text': company_bot.context
                },
            ]

            tag_context = company_bot.tag_context
            if not tag_context:
                default_response['exact_content'] = complete_content
                return default_response

            # Create analysis version if text is too long
            analysis_text = document_text
            max_analysis_chars = 10000

            if len(document_text) > max_analysis_chars:
                first_part = document_text[:max_analysis_chars // 2]
                last_part = document_text[-(max_analysis_chars // 2):]
                analysis_text = first_part + f"\n\n[SAMPLE - Full: {len(document_text)} chars]\n\n" + last_part

            # Include image information in context if available
            image_context = ""
            if extracted_images:
                image_context = f"\n\nDocument contains {len(extracted_images)} embedded images."
            context_data = {
                "document_text": analysis_text,
                "extracted_images": extracted_images,
                "master_tags": other_data.get('master_tag', None) if other_data else None
            }
            template = Template(tag_context)
            tag_context = template.render(context_data)

            messages = [{
                'role': 'user',
                'content': [{'text': f"{tag_context}"}]
            }]
            tool = company_bot.tool_context
            if tool and isinstance(tool, str):
                tool = json_repair.repair_json(tool, return_objects=True)
            print("Bedrock: Extraction call started.")
            response = handle_bedrock_model(
                system_prompt=system_prompt,
                messages=messages,
                model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature,
                max_token=company_bot.max_token,
                company_bot=company_bot,
                tools=tool
            )

            logger.info(f"Bedrock response type: {type(response)}")
            print(f"Bedrock response type: {type(response)}")
            print("--------\n\n")
            if response and isinstance(response, dict):
                # Extract the actual data from response
                extracted_data = response.pop("parameters", response.pop("input", response))
                if extracted_data and isinstance(extracted_data, dict):
                    # Preserve complete content
                    extracted_data['exact_content'] = complete_content

                    # Add images if available
                    if extracted_images:
                        extracted_data['images'] = extracted_images

                    # Validate and enhance result
                    result = self._validate_and_enhance_result(extracted_data, complete_content)
                    logger.info("Bedrock extraction successful")
                    return result

            default_response['exact_content'] = complete_content
            return default_response

        except Exception as e:
            logger.error(f"Bedrock extraction failed: {str(e)}")
            default_response['exact_content'] = document_text
            return default_response

    def process_document_with_links(
            self, text: str, company_bot, processed_urls=None,
            depth=0, max_depth=MAX_DEPTH, extracted_images: List[Dict[str, Any]] = None, other_data=None
    ) -> Dict[str, Any]:
        """Process document and extract content from linked documents recursively"""
        if processed_urls is None:
            processed_urls = set()

        if depth > max_depth:
            return {"subdocument": []}

        try:
            # Step 1: Extract basic content from current document using Bedrock
            logger.info(f"{'  ' * depth}Processing with Bedrock...")
            main_result = self.extract_basic_content(text, company_bot, extracted_images, other_data)

            # Step 2: Extract URLs from text
            logger.info(f"{'  ' * depth}Extracting URLs...")
            urls = self.extract_urls_from_text(text)
            main_result["url"] = urls

            # Step 3: Filter and process document URLs
            document_urls = [url for url in urls if self.is_document_url(url, depth)]
            logger.info(f"{'  ' * depth}Found {len(document_urls)} document URLs to process")

            subdocuments = []
            processed_count = 0

            for url in document_urls:
                if processed_count >= self.max_subdocs:
                    logger.warning(f"Maximum subdocuments limit ({self.max_subdocs}) reached")
                    break

                if url in processed_urls:
                    logger.info(f"{'  ' * depth}Skipping already processed: {url}")
                    continue

                logger.info(f"{'  ' * depth}Processing subdocument: {url}")
                processed_urls.add(url)

                if depth + 1 > max_depth:
                    logger.info(f"Skipping {url} - would exceed max depth")
                    continue

                # Extract text and images from URL
                linked_text, linked_images, linked_media_type = self.extract_text_from_url(url)

                if linked_text and len(linked_text.strip()) > 10:
                    logger.info(f"{'  ' * depth}Extracted {len(linked_text)} chars, {len(linked_images)} images")

                    # Recursively process the linked document
                    linked_result = self.process_document_with_links(
                        linked_text, company_bot, processed_urls, depth + 1, max_depth, linked_images,
                        other_data
                    )

                    if linked_result and linked_result.get('title'):
                        if linked_media_type:
                            linked_result['media_type'] = linked_media_type

                        subdocuments.append(linked_result)
                        processed_count += 1
                        logger.info(f"{'  ' * depth}Successfully processed: {linked_result.get('title')}")
            main_result["subdocument"] = subdocuments
            logger.info(f"{'  ' * depth}Completed depth {depth}. Subdocuments: {len(subdocuments)}")
            return main_result

        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            return {
                "title": "",
                "organization": "",
                "tags": [],
                # "exact_content": text,
                "summary": "",
                "document_type": "",
                "key_entities": [],
                "url": [],
                "subdocument": [],
                "images": extracted_images or []
            }

    def extract_with_bedrock(
            self, document_text, company_bot, extracted_images: List[Dict[str, Any]] = None, other_data=None
    ) -> Dict[
        str, Any]:
        """Main entry point - processes document with recursive link extraction"""
        try:
            logger.info("Starting document processing with recursive link extraction...")
            result = self.process_document_with_links(
                document_text, company_bot, extracted_images=extracted_images, other_data=other_data
            )
            return result
        except Exception as e:
            logger.error(f"Document processing failed: {str(e)}")
            return {
                "title": "",
                "organization": "",
                "tags": [],
                # "exact_content": document_text,
                "summary": "",
                "document_type": "",
                "key_entities": [],
                "url": [],
                "subdocument": [],
                "images": extracted_images or []
            }

    def extract_with_llm(self, text: str, company_bot=None, max_chars: int = 6000,
                         extracted_images: List[Dict[str, Any]] = None, other_data=None) -> Dict[str, Any]:
        """Extract structured information using AWS Bedrock Llama"""
        # Don't truncate - preserve complete content
        return self.extract_with_bedrock(
            document_text=text, company_bot=company_bot, extracted_images=extracted_images, other_data=other_data
        )

    def process_document_from_url(self, url: str, company_bot=None) -> Dict[str, Any]:
        """Process document directly from URL"""
        try:
            text_content, extracted_images, extracted_media_type = self.extract_text_from_url(url)

            if not text_content or len(text_content.strip()) < 10:
                raise ValueError("Document appears to be empty or unreadable")

            extracted_info = self.extract_with_llm(text_content, company_bot, extracted_images=extracted_images)

            result = {
                "file_path": url,
                "file_name": Path(url).name,
                "text_length": len(text_content),
                **extracted_info
            }

            return result

        except Exception as e:
            return {
                "error": str(e),
                "file_path": url,
                "file_name": "Unknown",
            }

    def process_document(self, file_path: str) -> Dict[str, Any]:
        """Process document from file path"""
        try:
            # Read document content with enhanced extraction
            text_content, extracted_images = self.extract_text_from_file(file_path, Path(file_path).suffix.strip('.'))

            if not text_content or len(text_content.strip()) < 10:
                raise ValueError("Document appears to be empty or unreadable")

            # Extract structured information using LLM
            extracted_info = self.extract_with_llm(text_content, extracted_images=extracted_images)

            # Add metadata
            result = {
                "file_path": str(file_path),
                "file_name": Path(file_path).name,
                "text_length": len(text_content),
                **extracted_info
            }

            return result

        except Exception as e:
            return {
                "error": str(e),
                "file_path": str(file_path),
                "file_name": Path(file_path).name if Path(file_path).exists() else "Unknown",
            }


# Additional helper functions for file object processing
def extract_tags_from_document_url(url: str, company_bot) -> Dict[str, Any]:
    """Extract structured information from document URL"""
    default_response = {
        "title": "",
        "organization": "",
        "tags": [],
        "exact_content": "",
        "summary": "",
        "document_type": "",
        "key_entities": [],
        "url": [],
        "subdocument": [],
        "images": []
    }
    try:
        extractor = DocumentExtractor()
        result = extractor.process_document_from_url(url, company_bot)
        return result
    except Exception as e:
        logger.error(f"Error extracting tags from URL: {e}")
        return default_response


def extract_tags_from_document_file(file, company_bot, file_extension: str, other_data) -> Dict[str, List[str]]:
    """Extract structured information from document file"""
    default_response = {
        "title": "",
        "organization": "",
        "tags": [],
        "exact_content": "",
        "summary": "",
        "document_type": "",
        "key_entities": [],
        "url": [],
        "subdocument": [],
        "images": []
    }
    try:
        extractor = DocumentExtractor()

        # Extract text and images from file
        document_text, extracted_images = extractor.extract_text_from_file(file, file_extension)

        if not document_text:
            return default_response

        # Extract information using Bedrock with URL processing
        result = extractor.extract_with_llm(
            document_text, company_bot, extracted_images=extracted_images, other_data=other_data
        )

        return result

    except Exception as e:
        logger.error(f"Error extracting tags from file: {e}")
        return default_response


def get_doc_tags_from_ai(file, company_bot, file_extension, other_data):
    """Main entry point for your code"""
    result = extract_tags_from_document_file(file, company_bot, file_extension, other_data)
    print("Final result: ", result)
    logger.info("Final Extraction Result:\n%s", json.dumps(result, indent=2, ensure_ascii=False))
    return result
