from typing import Dict, List, Any
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
from urllib.parse import urlparse
from chatbot.llm_models.llm_script import handle_bedrock_model


class DocumentExtractor:
    """Extract structured content from documents using AWS Bedrock Llama model with URL processing"""

    def extract_urls_from_text(self, text: str) -> List[str]:
        """Extract all URLs from text content"""
        try:
            # Pattern to match URLs
            url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
            urls = re.findall(url_pattern, text)

            # Remove duplicates while preserving order
            unique_urls = []
            seen = set()
            for url in urls:
                if url not in seen:
                    unique_urls.append(url)
                    seen.add(url)

            return unique_urls
        except Exception as e:
            print(f"Error extracting URLs: {e}")
            return []

    def is_document_url(self, url: str, depth: int = 0) -> bool:
        """Check if URL points to a document - ONLY .pdf, .docx, .txt at all levels"""
        try:
            # Exclude non-document URLs at all levels
            excluded_patterns = [
                'googleusercontent.com',  # Google images
                'gstatic.com',  # Google static files
                'chrome.google.com',  # Chrome extensions
                'googleapis.com',  # API endpoints
                '/favicon',  # Favicon files
                '.ico', '.png', '.jpg', '.jpeg', '.gif', '.svg',  # Icon/image files
                'forms.google.com'  # Google Forms
            ]

            for pattern in excluded_patterns:
                if pattern in url.lower():
                    return False

            # AT ALL LEVELS: Only accept .pdf, .docx, .txt
            # Check for Google Docs/Drive with these formats
            if 'docs.google.com/document' in url:
                # Google Docs are treated as .docx equivalent
                return True
            elif 'drive.google.com/file' in url:
                # Google Drive files - need to check if they're .pdf, .docx, .txt
                return True  # We'll let extract_text_from_url handle the format detection

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
            print(f"Error checking if URL is document: {e}")
            return False

    def convert_google_drive_url(self, url: str) -> str:
        """Convert Google URLs to downloadable formats - only for document types"""
        try:
            if 'docs.google.com/document' in url:
                # Extract document ID from Google Docs URL
                if '/d/' in url:
                    doc_id = url.split('/d/')[1].split('/')[0]
                    return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
            elif 'drive.google.com/file' in url:
                # Extract file ID from Google Drive URL - assume it's a document
                if '/d/' in url:
                    file_id = url.split('/d/')[1].split('/')[0]
                    return f"https://drive.google.com/uc?id={file_id}&export=download"

            # Skip Google Sheets - not in our accepted formats
            if 'docs.google.com/spreadsheets' in url:
                return None

            return url
        except Exception as e:
            print(f"Error converting Google Drive URL: {e}")
            return url

    def extract_text_from_url(self, url: str) -> str:
        """Extract text content from document URL with proper Google Docs support"""
        try:
            print(f"Extracting text from: {url}")

            # Convert Google Drive URLs to downloadable format
            download_url = self.convert_google_drive_url(url)
            if download_url is None:
                print(f"Skipped non-document URL: {url}")
                return ""
            if download_url != url:
                print(f"Converted to: {download_url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            response = requests.get(download_url, headers=headers, timeout=30)
            response.raise_for_status()

            # Handle Google Docs text export directly
            if 'docs.google.com' in download_url and 'export?format=txt' in download_url:
                content = response.text
                print(f"Successfully extracted {len(content)} characters from Google Doc")
                return content

            # For other file types, save to temp file and process
            content_type = response.headers.get('content-type', '').lower()
            file_extension = 'txt'  # Default

            if 'pdf' in content_type:
                file_extension = 'pdf'
            elif 'word' in content_type or 'document' in content_type:
                file_extension = 'docx'
            else:
                # Try to get extension from URL
                parsed_url = urlparse(url)
                path_ext = Path(parsed_url.path).suffix.lower().strip('.')
                if path_ext in ['pdf', 'docx', 'txt']:
                    file_extension = path_ext

            print(f"Processing as {file_extension} file")

            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name

            try:
                extracted_text = self.extract_text_from_file(temp_file_path, file_extension)
                print(f"Successfully extracted {len(extracted_text)} characters")
                return extracted_text
            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            print(f"Failed to extract text from URL {url}: {e}")
            return ""

    def extract_text_from_file(self, file, file_extension: str) -> str:
        """
        Extract text content from various file types

        Args:
            file: File object (Django UploadedFile or file path)
            file_extension: File extension (pdf, doc, docx, txt, csv, xls, xlsx)

        Returns:
            Extracted text as string
        """
        try:
            file_extension = file_extension.lower().strip('.')

            # Handle file path vs file object
            if isinstance(file, (str, Path)):
                file_path = Path(file)
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found: {file_path}")

                if file_extension == 'pdf':
                    with open(file_path, 'rb') as f:
                        return self._extract_pdf_text(f)
                elif file_extension in ['doc', 'docx']:
                    return self._extract_docx_text(file_path)
                elif file_extension == 'txt':
                    return self._extract_txt_text(file_path)
                elif file_extension == 'csv':
                    return self._extract_csv_text(file_path)
                elif file_extension in ['xls', 'xlsx']:
                    return self._extract_excel_text(file_path)
            else:
                # Handle file object
                if file_extension == 'pdf':
                    return self._extract_pdf_text(file)
                elif file_extension in ['doc', 'docx']:
                    return self._extract_docx_text_from_object(file)
                elif file_extension == 'txt':
                    return self._extract_txt_text_from_object(file)
                elif file_extension == 'csv':
                    return self._extract_csv_text_from_object(file)
                elif file_extension in ['xls', 'xlsx']:
                    return self._extract_excel_text_from_object(file)

            # Try to read as text for unknown file types
            if isinstance(file, (str, Path)):
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            else:
                content = file.read()
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='ignore')
                return content

        except Exception as e:
            print(f"Error extracting text from file: {e}")
            return ""

    def _extract_pdf_text(self, file) -> str:
        """Extract text from PDF"""
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
            return self.extract_text_from_file(file_path, file_ext)
        except Exception as e:
            raise Exception(f"Error reading document: {str(e)}")

    def extract_basic_content(self, document_text, company_bot) -> Dict[str, Any]:
        """Extract basic content using Bedrock without link processing"""
        default_response = {
            "title": "",
            "organization": "",
            "tags": [],
            "exact_content": "",
            "summary": "",
            "document_type": "",
            "key_entities": [],
            "url": [],
            "subdocument": []
        }

        try:
            print("Processing content with Bedrock...")

            system_prompt = [
                {
                    'text': company_bot.context
                },
            ]
            tag_context = company_bot.tag_context
            if not tag_context:
                return default_response

            context_data = {
                "document_text": document_text,
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

            response = handle_bedrock_model(
                system_prompt=system_prompt, messages=messages, model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot,
                tools=tool
            )

            print("response: ", response)
            print("type: response: ", type(response))

            if response and isinstance(response, dict):
                extracted_data = response.pop("parameters", response.pop("input", None))
                if extracted_data and isinstance(extracted_data, dict):
                    response.clear()
                    response.update(extracted_data)
                print("last response: ", response)
                print("last type: response: ", type(response))
                return response
            else:
                result = default_response

            print(f"Bedrock extraction successful: {result}")
            return default_response

        except Exception as e:
            print(f"Bedrock extraction failed: {str(e)}")
            return default_response

    def process_document_with_links(self, text: str, company_bot, processed_urls=None, depth=0, max_depth=3) -> Dict[
        str, Any]:
        """Process document and extract content from linked documents recursively"""
        if processed_urls is None:
            processed_urls = set()

        # print(f"{'  ' * depth}Processing document at depth {depth}")

        if depth > max_depth:
            # print(f"{'  ' * depth}Reached maximum depth {max_depth}")
            return {"subdocument": []}

        # Step 1: Extract basic content from current document using Bedrock
        print(f"{'  ' * depth}Step 1: Processing with Bedrock...")
        main_result = self.extract_basic_content(text, company_bot)

        # Step 2: Manually extract URLs from text
        print(f"{'  ' * depth}Step 2: Extracting URLs manually...")
        urls = self.extract_urls_from_text(text)

        # Step 3: Filter URLs - ONLY .pdf, .docx, .txt at ALL levels
        print(f"{'  ' * depth}Step 3: Filtering URLs (ONLY .pdf, .docx, .txt accepted)...")
        document_urls = []
        all_urls = []

        for url in urls:
            all_urls.append(url)
            # Same strict filtering at all levels - only .pdf, .docx, .txt
            if self.is_document_url(url, depth):
                document_urls.append(url)
                print(f"{'  ' * depth}  ACCEPT: {url}")
            else:
                print(f"{'  ' * depth}  REJECT: {url}")

        main_result["url"] = all_urls
        main_result["subdocument"] = []

        print(f"{'  ' * depth}Document URLs to process: {len(document_urls)}")

        # Step 4: Process each document URL
        for i, url in enumerate(document_urls):
            if url in processed_urls:
                print(f"{'  ' * depth}Skipping already processed: {url}")
                continue

            print(f"{'  ' * depth}Processing document {i + 1}/{len(document_urls)}: {url}")
            processed_urls.add(url)

            # Step 5: Download and extract text
            linked_text = self.extract_text_from_url(url)

            if linked_text and len(linked_text.strip()) > 10:
                print(f"{'  ' * depth}  Extracted {len(linked_text)} characters")

                # Step 6: Recursively process the linked document
                print(f"{'  ' * depth}  Recursively processing linked content...")
                linked_result = self.process_document_with_links(
                    linked_text, company_bot, processed_urls, depth + 1, max_depth
                )

                if linked_result and linked_result.get('title'):
                    print(f"{'  ' * depth}  Successfully processed: {linked_result.get('title')}")
                    main_result["subdocument"].append(linked_result)
                else:
                    print(f"{'  ' * depth}  Failed to process linked document")
            else:
                print(f"{'  ' * depth}  Could not extract content from: {url}")

        print(f"{'  ' * depth}Completed depth {depth}. Subdocuments: {len(main_result['subdocument'])}")
        return main_result

    def extract_with_bedrock(self, document_text, company_bot) -> Dict[str, List[str]]:
        """Main entry point - processes document with recursive link extraction"""
        try:
            print("Starting document processing with recursive link extraction...")
            result = self.process_document_with_links(document_text, company_bot)
            return result
        except Exception as e:
            print(f"Document processing failed: {str(e)}")
            return {
                "title": "",
                "organization": "",
                "tags": [],
                "exact_content": "",
                "summary": "",
                "document_type": "",
                "key_entities": [],
                "url": [],
                "subdocument": []
            }

    def extract_with_llm(self, text: str, company_bot=None, max_chars: int = 6000) -> Dict[str, Any]:
        """Extract structured information using AWS Bedrock Llama"""

        # Truncate if text is too long
        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        return self.extract_with_bedrock(document_text=text, company_bot=company_bot)

    def process_document_from_url(self, url: str, company_bot=None) -> Dict[str, Any]:
        """Process document directly from URL"""
        try:
            text_content = self.extract_text_from_url(url)

            if not text_content or len(text_content.strip()) < 10:
                raise ValueError("Document appears to be empty or unreadable")

            extracted_info = self.extract_with_llm(text_content, company_bot)

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
        try:
            # Read document content
            text_content = self.read_document(file_path)

            if not text_content or len(text_content.strip()) < 10:
                raise ValueError("Document appears to be empty or unreadable")

            # Extract structured information using LLM
            extracted_info = self.extract_with_llm(text_content)

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
        "subdocument": []
    }
    try:
        extractor = DocumentExtractor()
        result = extractor.process_document_from_url(url, company_bot)
        return result
    except Exception as e:
        print(f"Error extracting tags from URL: {e}")
        return default_response


def extract_tags_from_document_file(file, company_bot, file_extension: str) -> Dict[str, List[str]]:
    default_response = {
        "title": "",
        "organization": "",
        "tags": [],
        "exact_content": "",
        "summary": "",
        "document_type": "",
        "key_entities": [],
        "url": [],
        "subdocument": []
    }
    try:
        extractor = DocumentExtractor()

        # Extract text from file
        document_text = extractor.extract_text_from_file(file, file_extension)

        if not document_text:
            return default_response

        # Extract information using Bedrock with URL processing
        result = extractor.extract_with_llm(document_text, company_bot)

        return result

    except Exception as e:
        print(f"Error extracting tags from file: {e}")
        return default_response


def get_doc_tags_from_ai(file, company_bot, file_extension):
    result = extract_tags_from_document_file(file, company_bot, file_extension)
    # auto_tags = result.get('tags', [])
    # print(f"Tags: {auto_tags}")
    return result
