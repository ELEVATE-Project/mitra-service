"""Main DocumentExtractor class that coordinates all extraction functionality"""

import io
import logging
from typing import Dict, List, Any, Set, Tuple
from pathlib import Path
from urllib.parse import urlparse
from chatbot.models import FileTypeChoices
from chatbot.utils.knowledge_service.base.extraction_config import MAX_DEPTH
from .docx_extractor import DOCXExtractor
from .excel_extractor import ExcelExtractor
from .pdf_extractor import PDFExtractor
from .text_extractor import CSVExtractor, TXTExtractor
from .url_extractor import URLExtractor
from chatbot.utils.knowledge_service.processor.url_processor import DocumentURLProcessor
from chatbot.utils.knowledge_service.processor.image_processor import ImageProcessor
from chatbot.utils.knowledge_service.processor.ai_processor import AIContentProcessor
from chatbot.utils.knowledge_service.base.extraction_utils import (
    normalize_url_for_tracking, get_comprehensive_content_for_url_extraction, convert_google_drive_url
)


logger = logging.getLogger('django')


class DocumentExtractor:
    """
    Extract structured content from documents using AWS Bedrock Llama model with enhanced features
    """

    def __init__(
            self, max_depth: int = MAX_DEPTH, max_subdocs: int = 10, enable_ocr: bool = True,
            compress_images: bool = True, extract_images: bool = False, main_doc_max_chars: int = 3000,
            subdoc_max_chars: int = 500, excel_max_rows: int = 50, excel_max_cols: int = 20,
            max_file_size_mb: int = 50
    ):
        """Initialize with enhanced features and configurable limits"""
        self.max_depth = max_depth
        self.max_subdocs = max_subdocs
        self.processed_urls: Set[str] = set()
        self.url_cache: Dict[str, str] = {}
        self.enable_ocr = enable_ocr
        self.compress_images = compress_images
        self.extract_images = extract_images  # Control image extraction

        # Configurable text limits
        self.main_doc_max_chars = main_doc_max_chars
        self.subdoc_max_chars = subdoc_max_chars
        self.excel_max_rows = excel_max_rows
        self.excel_max_cols = excel_max_cols

        # File validation
        self.allowed_extensions = {'.pdf', '.doc', '.docx', '.txt', '.csv', '.xls', '.xlsx'}
        self.max_file_size_mb = max_file_size_mb
        self.max_file_size_bytes = self.max_file_size_mb * 1024 * 1024

        # Initialize components
        self.url_extractor = URLExtractor()
        self.url_processor = DocumentURLProcessor(self.url_cache, max_file_size_mb)
        self.image_processor = ImageProcessor(enable_ocr, compress_images, extract_images)
        self.ai_processor = AIContentProcessor(main_doc_max_chars)

        # Initialize file extractors
        self.pdf_extractor = PDFExtractor(self.image_processor)
        self.docx_extractor = DOCXExtractor(self.image_processor)
        self.excel_extractor = ExcelExtractor(excel_max_rows, excel_max_cols, subdoc_max_chars)
        self.csv_extractor = CSVExtractor(excel_max_rows, excel_max_cols)
        self.txt_extractor = TXTExtractor()

    def extract_text_from_url(self, url: str, is_subdoc: bool = False) -> Tuple[
        str, List[Dict[str, Any]], Any, Dict[str, Any], str]:
        """Extract text content and images from document URL, with error handling

        Returns: (text, images, media_type, error_info, full_text_for_url_extraction)
        """
        max_chars = self.subdoc_max_chars if is_subdoc else self.main_doc_max_chars

        try:
            # Download document
            content_bytes, error_info, content_type = self.url_processor.download_document(url, is_subdoc)

            if error_info:
                return "", [], None, error_info, ""

            if not content_bytes:
                return "", [], None, None, ""

            is_pdf, is_excel, is_csv, is_docx, is_txt = self.url_processor.determine_file_type(
                content_bytes, content_type, url
            )

            text = ""
            images = []
            full_text_for_url_extraction = ""
            extracted_hyperlinks = []
            media_type = None

            # Extract content based on file type
            if is_pdf:
                full_text_for_url_extraction, extracted_hyperlinks = self.pdf_extractor.extract_comprehensive_content_for_urls(
                    content_bytes)
                text = self.pdf_extractor.extract_text_enhanced(content_bytes)
                images = self.image_processor.extract_images_from_pdf_pymupdf(content_bytes)
                media_type = FileTypeChoices.PDF
                logger.info(f"Assigned media type as: {media_type}")

            elif is_excel or 'officedocument.spreadsheet' in content_type:
                logger.info("Excel file detected - extracting comprehensive content for URL detection...")
                full_text_for_url_extraction, extracted_hyperlinks = self.excel_extractor.extract_comprehensive_content_for_urls(
                    content_bytes)
                text = self.excel_extractor.extract_limited_content(content_bytes, max_chars)
                media_type = FileTypeChoices.XLSX
                logger.info(f"Excel processing complete:")
                logger.info(f"  - Limited content for LLM: {len(text)} chars")
                logger.info(f"  - Comprehensive content for URLs: {len(full_text_for_url_extraction)} chars")
                logger.info(f"  - Hyperlinks extracted: {len(extracted_hyperlinks)}")

            elif is_csv:
                full_text_for_url_extraction, extracted_hyperlinks = self.csv_extractor.extract_comprehensive_content_for_urls(
                    content_bytes)
                # Process CSV with limited extraction for LLM
                try:
                    import pandas as pd
                    df = pd.read_csv(io.BytesIO(content_bytes), nrows=self.excel_max_rows)
                    if len(df.columns) > self.excel_max_cols:
                        df = df.iloc[:, :self.excel_max_cols]
                    text = df.to_string(max_rows=self.excel_max_rows, max_cols=self.excel_max_cols)
                    if len(text) > max_chars:
                        text = text[:max_chars] + "\n...[Content truncated]"
                    media_type = FileTypeChoices.CSV
                except Exception as e:
                    logger.error(f"Error processing CSV: {e}")
                    text = content_bytes.decode('utf-8', errors='ignore')[:max_chars]
                    media_type = FileTypeChoices.CSV

            elif is_docx:
                logger.info("DOCX file detected - extracting comprehensive content for URL detection...")
                full_text_for_url_extraction, extracted_hyperlinks = self.docx_extractor.extract_comprehensive_content_for_urls(
                    content_bytes)

                # Extract limited content for LLM processing
                import tempfile
                import os
                import docx

                with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
                    temp_file.write(content_bytes)
                    temp_file_path = temp_file.name

                try:
                    doc = docx.Document(temp_file_path)
                    text_parts = []
                    for para in doc.paragraphs:
                        if para.text.strip():
                            text_parts.append(para.text)
                    text = '\n'.join(text_parts)
                    media_type = FileTypeChoices.DOCX
                    logger.info(f"Assigned media type as: {media_type}")
                finally:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)

                images = self.image_processor.extract_images_from_docx(content_bytes)
                logger.info(f"DOCX processing complete:")
                logger.info(f"  - Limited content for LLM: {len(text)} chars")
                logger.info(f"  - Comprehensive content for URLs: {len(full_text_for_url_extraction)} chars")
                logger.info(f"  - Hyperlinks extracted: {len(extracted_hyperlinks)}")

            else:
                logger.info("TXT/Other file detected - extracting content...")
                full_text_for_url_extraction, extracted_hyperlinks = self.txt_extractor.extract_comprehensive_content_for_urls(
                    content_bytes)
                text = content_bytes.decode('utf-8', errors='ignore')
                media_type = FileTypeChoices.TXT
                logger.info(f"Assigned media type as: {media_type}")

            # Combine text-based URLs with hyperlink URLs for ALL formats
            combined_urls = []
            combined_urls.extend(extracted_hyperlinks)
            text_urls = self.url_extractor.extract_urls_from_text(full_text_for_url_extraction)
            for url_found in text_urls:
                if url_found not in combined_urls:
                    combined_urls.append(url_found)

            # Store combined URLs for later use by appending hyperlinks to full text
            if extracted_hyperlinks:
                full_text_for_url_extraction = full_text_for_url_extraction + "\n\n=== EXTRACTED HYPERLINKS ===\n" + "\n".join(
                    extracted_hyperlinks)

            logger.info(f"URL extraction summary for {url}:")
            logger.info(f"  - Hyperlinks extracted: {len(extracted_hyperlinks)}")
            logger.info(f"  - Text-based URLs found: {len(text_urls)}")
            logger.info(f"  - Total unique URLs for processing: {len(combined_urls)}")

            # Apply character limit for subdocuments AFTER storing full text
            if is_subdoc and len(text) > max_chars:
                text = text[:max_chars] + "\n...[Content truncated]"

            # Final validation - check if we got meaningful content
            if not text or len(text.strip()) < 10:
                logger.warning(f"No meaningful content extracted from {url}")
                error_info = {
                    'error': f'No content could be extracted from {url}',
                    'error_type': 'no_content',
                    'url': url
                }
                self.url_cache[url] = error_info
                return "", [], None, error_info, ""

            if text:
                self.url_cache[url] = text

            logger.info(
                f"For url: {url}, Extracted {len(text)} characters and {len(images)} "
                f"images and file type as {media_type}"
            )

            return text, images, media_type, None, full_text_for_url_extraction

        except Exception as e:
            error_info = {
                'error': f'Failed to extract from {url}: {str(e)}',
                'error_type': 'extraction_error',
                'url': url
            }
            logger.error(f"Failed to extract from URL {url}: {e}")
            self.url_cache[url] = error_info
            return "", [], None, error_info, ""

    def extract_text_from_file(self, file, file_extension: str) -> Tuple[str, List[Dict[str, Any]], str]:
        """Extract text content and images from various file types

        Returns: (limited_text_for_llm, images, comprehensive_text_for_urls)
        """
        try:
            import pandas as pd

            file_extension = file_extension.lower().strip('.')
            text = ""
            images = []
            comprehensive_text_for_urls = ""

            # Handle file path vs file object
            if isinstance(file, (str, Path)):
                file_path = Path(file)
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found: {file_path}")

                if file_extension == 'pdf':
                    with open(file_path, 'rb') as f:
                        content_bytes = f.read()
                    text = self.pdf_extractor.extract_text_enhanced(content_bytes)
                    comprehensive_text_for_urls, _ = self.pdf_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                    images = self.image_processor.extract_images_from_pdf_pymupdf(content_bytes)
                elif file_extension in ['doc', 'docx']:
                    with open(file_path, 'rb') as f:
                        content_bytes = f.read()
                    text = self.docx_extractor.extract_text(file_path)
                    comprehensive_text_for_urls, _ = self.docx_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                    images = self.image_processor.extract_images_from_docx(content_bytes)
                elif file_extension == 'txt':
                    with open(file_path, 'rb') as f:
                        content_bytes = f.read()
                    text = self.txt_extractor.extract_text(file_path)
                    comprehensive_text_for_urls, _ = self.txt_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                elif file_extension == 'csv':
                    with open(file_path, 'rb') as f:
                        content_bytes = f.read()
                    text = self.csv_extractor.extract_text(file_path)
                    comprehensive_text_for_urls, _ = self.csv_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                elif file_extension in ['xls', 'xlsx']:
                    with open(file_path, 'rb') as f:
                        content_bytes = f.read()
                    text = self.excel_extractor.extract_text(file_path)
                    comprehensive_text_for_urls, extracted_hyperlinks = self.excel_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                    # Combine with hyperlinks
                    if extracted_hyperlinks:
                        comprehensive_text_for_urls = comprehensive_text_for_urls + "\n\n=== EXTRACTED HYPERLINKS ===\n" + "\n".join(
                            extracted_hyperlinks)
                    logger.info(
                        f"Main Excel file - Limited content: {len(text)} chars, Comprehensive: {len(comprehensive_text_for_urls)} chars, Hyperlinks: {len(extracted_hyperlinks)}")
                else:
                    # Default case
                    comprehensive_text_for_urls = text
            else:
                # Handle file object
                if file_extension == 'pdf':
                    file.seek(0)
                    content_bytes = file.read()
                    text = self.pdf_extractor.extract_text_enhanced(content_bytes)
                    comprehensive_text_for_urls, _ = self.pdf_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                    images = self.image_processor.extract_images_from_pdf_pymupdf(content_bytes)
                elif file_extension in ['doc', 'docx']:
                    file.seek(0)
                    content_bytes = file.read()
                    text = self.docx_extractor.extract_text_from_object(io.BytesIO(content_bytes))
                    comprehensive_text_for_urls, _ = self.docx_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                    images = self.image_processor.extract_images_from_docx(content_bytes)
                elif file_extension == 'txt':
                    file.seek(0)
                    content_bytes = file.read()
                    text = self.txt_extractor.extract_text_from_object(file)
                    comprehensive_text_for_urls, _ = self.txt_extractor.extract_comprehensive_content_for_urls(
                        content_bytes if isinstance(content_bytes, bytes) else content_bytes.encode('utf-8'))
                elif file_extension == 'csv':
                    file.seek(0)
                    content_bytes = file.read()
                    text = self.csv_extractor.extract_text_from_object(file)
                    comprehensive_text_for_urls, _ = self.csv_extractor.extract_comprehensive_content_for_urls(
                        content_bytes if isinstance(content_bytes, bytes) else content_bytes.encode('utf-8'))
                elif file_extension in ['xls', 'xlsx']:
                    file.seek(0)
                    content_bytes = file.read()
                    text = self.excel_extractor.extract_text_from_object(file)
                    comprehensive_text_for_urls, extracted_hyperlinks = self.excel_extractor.extract_comprehensive_content_for_urls(
                        content_bytes)
                    # Combine with hyperlinks
                    if extracted_hyperlinks:
                        comprehensive_text_for_urls = comprehensive_text_for_urls + "\n\n=== EXTRACTED HYPERLINKS ===\n" + "\n".join(
                            extracted_hyperlinks)
                    logger.info(
                        f"Main Excel file - Limited content: {len(text)} chars, Comprehensive: {len(comprehensive_text_for_urls)} chars, Hyperlinks: {len(extracted_hyperlinks)}")
                else:
                    # Default case
                    comprehensive_text_for_urls = text

            return text, images, comprehensive_text_for_urls

        except Exception as e:
            logger.error(f"Error extracting from file: {e}")
            return "", [], ""

    def read_document(self, file_path: str) -> str:
        """Extract text content from various document formats"""
        file_path = Path(file_path)
        file_ext = file_path.suffix.lower().strip('.')

        try:
            text, _, _ = self.extract_text_from_file(file_path, file_ext)
            return text
        except Exception as e:
            raise Exception(f"Error reading document: {str(e)}")

    def process_document_with_links(
            self, text: str, company_bot, comprehensive_text: str = None, processed_urls=None,
            depth=0, max_depth=MAX_DEPTH, extracted_images: List[Dict[str, Any]] = None, other_data=None
    ) -> Dict[str, Any]:
        """Process document and extract links from linked documents with enhanced URL extraction for ALL formats"""
        if processed_urls is None:
            processed_urls = set()

        try:
            # Step 1: Extract basic content from current document using Bedrock
            logger.info(f"{'  ' * depth}Processing main document with Bedrock...")
            main_result = self.ai_processor.extract_basic_content(text, company_bot, extracted_images, other_data)

            # Use comprehensive text for URL extraction
            url_extraction_text = comprehensive_text if comprehensive_text else text

            # Step 2: Extract URLs from comprehensive document content
            logger.info(f"{'  ' * depth}Extracting URLs from main document...")
            logger.info(f"{'  ' * depth}  - Using comprehensive content: {len(url_extraction_text)} chars")
            logger.info(f"{'  ' * depth}  - Limited text for LLM: {len(text)} chars")

            urls = self.url_extractor.extract_urls_from_text(url_extraction_text)  # NOW USING COMPREHENSIVE TEXT
            main_result["url"] = urls

            # Log all extracted URLs
            logger.info(f"{'  ' * depth}Total URLs extracted from main document: {len(urls)}")

            # Step 3: Process links
            subdocuments = []
            failed_links = []

            # Filter for document URLs
            document_urls = [url for url in urls if self.url_extractor.is_document_url(url, depth)]
            logger.info(f"{'  ' * depth}Found {len(document_urls)} document URLs in main document")

            # Process each document URL from the main document
            for main_doc_url in document_urls:
                # Normalize URL for deduplication
                normalized_url = normalize_url_for_tracking(main_doc_url)

                if normalized_url in processed_urls:
                    logger.info(f"{'  ' * depth}Skipping already processed URL: {main_doc_url}")
                    continue

                logger.info(f"{'  ' * depth}Processing linked document: {main_doc_url}")
                processed_urls.add(normalized_url)

                # Extract content from this linked document
                linked_text, linked_images, linked_media_type, error_info, full_text_for_urls = self.extract_text_from_url(
                    main_doc_url, is_subdoc=True
                )

                if error_info:
                    # Enhanced error handling for different error types
                    if error_info.get('error_type') == 'unsupported_format':
                        error_info['error'] = f"Unsupported file format: {error_info['error']}"

                    failed_links.append({
                        "file_url": main_doc_url,
                        "error": error_info,
                        "source_document": "main"
                    })
                    continue

                if linked_text and len(linked_text.strip()) > 10:
                    # Check if media type was determined
                    if linked_media_type is None:
                        logger.warning(f"Could not determine valid media type for {main_doc_url}")
                        failed_links.append({
                            "file_url": main_doc_url,
                            "error": {
                                'error': 'Could not determine valid file type',
                                'error_type': 'unknown_format',
                                'url': main_doc_url
                            },
                            "source_document": "main"
                        })
                        continue

                    # Extract URLs from the COMPREHENSIVE text for ALL file formats
                    logger.info(f"{'  ' * depth}Extracting URLs from linked document: {main_doc_url}")
                    logger.info(f"{'  ' * depth}  - Media type: {linked_media_type}")
                    logger.info(f"{'  ' * depth}  - Using comprehensive content: {len(full_text_for_urls)} chars")

                    # Extract URLs from the comprehensive content (now includes hyperlinks for all formats)
                    links_in_subdoc = self.url_extractor.extract_urls_from_text(full_text_for_urls)
                    logger.info(f"{'  ' * depth}Found {len(links_in_subdoc)} total links inside {main_doc_url}")

                    # Filter for document URLs
                    subdoc_document_urls = [url for url in links_in_subdoc if
                                            self.url_extractor.is_document_url(url, depth)]
                    logger.info(f"{'  ' * depth}Found {len(subdoc_document_urls)} document URLs inside {main_doc_url}")

                    # Process each document URL found within the linked document
                    subdoc_count = 0
                    for sub_url in subdoc_document_urls:
                        if subdoc_count >= self.max_subdocs:
                            logger.info(f"{'  ' * (depth + 1)}Reached max subdocs limit ({self.max_subdocs})")
                            break

                        # Normalize URL for deduplication
                        normalized_sub_url = normalize_url_for_tracking(sub_url)

                        if normalized_sub_url in processed_urls:
                            logger.info(f"{'  ' * (depth + 1)}Skipping already processed subdocument URL: {sub_url}")
                            continue

                        logger.info(f"{'  ' * (depth + 1)}Processing subdocument: {sub_url}")
                        processed_urls.add(normalized_sub_url)
                        subdoc_count += 1

                        # Extract content from subdocument URL
                        sub_text, sub_images, sub_media_type, sub_error_info, _ = self.extract_text_from_url(
                            sub_url, is_subdoc=True
                        )
                        logger.info(f"for url: {sub_url}, extracted sub_text is: {sub_text}")

                        if sub_error_info:
                            logger.info(f"{'  ' * (depth + 1)}Subdocument failed: {sub_error_info}")

                            # Enhance error message for unsupported formats
                            if sub_error_info.get('error_type') == 'unsupported_format':
                                sub_error_info[
                                    'error'] = f"Unsupported file format in linked document: {sub_error_info['error']}"

                            failed_links.append({
                                "file_url": sub_url,
                                "error": sub_error_info,
                                "source_document": main_doc_url
                            })
                        else:
                            # Successfully accessed - process subdocument with LLM
                            if sub_text and len(sub_text.strip()) > 10:
                                # Get the downloadable URL
                                downloadable_url = convert_google_drive_url(sub_url)

                                # Check if media type was determined
                                if sub_media_type is None:
                                    logger.warning(f"Could not determine valid media type for {sub_url}")
                                    failed_links.append({
                                        "file_url": sub_url,
                                        "error": {
                                            'error': 'Could not determine valid file type',
                                            'error_type': 'unknown_format',
                                            'url': sub_url
                                        },
                                        "source_document": main_doc_url
                                    })
                                    continue

                                # Process subdocument content with Bedrock
                                subdoc_result = self.ai_processor.extract_basic_content(
                                    sub_text,
                                    company_bot,
                                    sub_images,
                                    other_data,
                                    is_subdoc=True
                                )

                                # Check for any extraction errors in subdocument
                                if (subdoc_result.get('title_extraction_failed') or
                                        subdoc_result.get('extraction_error') or
                                        subdoc_result.get('error') or
                                        subdoc_result.get('error_type')):
                                    error_message = (subdoc_result.get('error') or
                                                     subdoc_result.get('extraction_error') or
                                                     'LLM failed to extract title from subdocument')

                                    error_type = (subdoc_result.get('error_type') or
                                                  'title_extraction_failed')

                                    logger.error(f"Subdocument extraction failed for {sub_url}: {error_message}")
                                    failed_links.append({
                                        "file_url": sub_url,
                                        "error": {
                                            'error': error_message,
                                            'error_type': error_type,
                                            'url': sub_url
                                        },
                                        "source_document": main_doc_url
                                    })
                                    continue

                                # Create subdocument entry (without "url" field)
                                subdoc_entry = {
                                    "title": subdoc_result.get(
                                        "title",
                                        f"Document from {Path(urlparse(main_doc_url).path).name or 'linked document'}"
                                    ),
                                    "file_url": downloadable_url,
                                    "media_type": sub_media_type,
                                    "source_document": main_doc_url,
                                    "exact_content": sub_text,
                                    "summary": subdoc_result.get("summary", ""),
                                    "tags": subdoc_result.get("tags", []),
                                    "organization": subdoc_result.get("organization", ""),
                                    "document_type": subdoc_result.get("document_type", ""),
                                    "key_entities": subdoc_result.get("key_entities", []),
                                    "subdocument": [],
                                    "images": sub_images or []
                                }
                                subdocuments.append(subdoc_entry)
                            else:
                                logger.warning(f"Subdocument {sub_url} has insufficient content")
                                failed_links.append({
                                    "file_url": sub_url,
                                    "error": {
                                        'error': 'Document has insufficient content (less than 10 characters)',
                                        'error_type': 'insufficient_content',
                                        'url': sub_url
                                    },
                                    "source_document": main_doc_url
                                })
                else:
                    logger.warning(f"Linked document {main_doc_url} has insufficient content: {linked_text}")
                    failed_links.append({
                        "file_url": main_doc_url,
                        "error": {
                            'error': 'Document has insufficient content (less than 10 characters)',
                            'error_type': 'insufficient_content',
                            'url': main_doc_url
                        },
                        "source_document": "main"
                    })

            main_result["subdocument"] = subdocuments
            main_result["failed_links"] = failed_links

            # Log summary
            logger.info(f"{'  ' * depth}Processing complete:")
            logger.info(f"{'  ' * depth}  - URLs in main document: {len(urls)}")
            logger.info(f"{'  ' * depth}  - Document URLs in main: {len(document_urls)}")
            logger.info(f"{'  ' * depth}  - Successfully processed subdocuments: {len(subdocuments)}")
            logger.info(f"{'  ' * depth}  - Failed: {len(failed_links)}")
            logger.info(f"{'  ' * depth}  - Total URLs processed: {len(processed_urls)}")

            return main_result

        except ValueError as ve:
            logger.error(f"Main document processing failed: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "title": "",
                "organization": "",
                "tags": [],
                "exact_content": text,
                "summary": "",
                "document_type": "",
                "key_entities": [],
                "url": [],
                "subdocument": [],
                "failed_links": [],
                "images": extracted_images or []
            }

    def extract_with_bedrock(self, document_text, company_bot,
                             extracted_images: List[Dict[str, Any]] = None,
                             other_data=None) -> Dict[str, Any]:
        """Main entry point - processes document with recursive link extraction"""
        try:
            logger.info("Starting document processing with recursive link extraction...")

            # Get comprehensive content for URL extraction
            comprehensive_text_for_urls = get_comprehensive_content_for_url_extraction(
                document_text, other_data
            )

            result = self.process_document_with_links(
                text=document_text,  # Limited text for LLM
                comprehensive_text=comprehensive_text_for_urls,  # Full text for URL extraction
                company_bot=company_bot,
                extracted_images=extracted_images,
                other_data=other_data
            )
            return result
        except ValueError as ve:
            # Re-raise ValueError so it can be handled by the calling function
            logger.error(f"Document processing validation failed: {str(ve)}")
            raise  # This allows the error to propagate to get_doc_tags_from_ai()
        except Exception as e:
            logger.error(f"Document processing failed with unexpected error: {str(e)}")
            return {
                "title": "",
                "organization": "",
                "tags": [],
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
            document_text=text, company_bot=company_bot,
            extracted_images=extracted_images, other_data=other_data
        )

    def process_document_from_url(self, url: str, company_bot=None) -> Dict[str, Any]:
        """Process document directly from URL"""
        try:
            text_content, extracted_images, extracted_media_type, error_info, _ = self.extract_text_from_url(
                url, is_subdoc=False
            )

            if error_info:
                return {
                    "error": error_info['error'],
                    "error_type": error_info.get('error_type', 'unknown'),
                    "file_path": url,
                    "file_name": Path(url).name,
                }

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

    def process_document(self, file_path: str, company_bot=None, other_data=None) -> Dict[str, Any]:
        """Process document from file path"""
        try:
            # Read document content with enhanced extraction
            text_content, extracted_images, comprehensive_text_for_urls = self.extract_text_from_file(
                file_path, Path(file_path).suffix.strip('.')
            )

            if not text_content or len(text_content.strip()) < 10:
                raise ValueError("Document appears to be empty or unreadable")

            # Extract structured information using LLM
            extracted_info = self.extract_with_llm(
                text=text_content,
                company_bot=company_bot,
                extracted_images=extracted_images,
                other_data=other_data,
            )

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