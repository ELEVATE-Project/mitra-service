from typing import Dict, List, Any
from pathlib import Path
import PyPDF2
import docx
import pandas as pd
from jinja2 import Template
import json_repair
from chatbot.llm_models.llm_script import handle_bedrock_model


class DocumentExtractor:
    """Extract structured content from documents using AWS Bedrock Llama model"""

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

    def extract_with_bedrock(self, document_text, company_bot) -> Dict[str, List[str]]:
        default_response = {
            "title": "",
            "organization": "",
            "tags": [],
            "exact_content": "",
            "summary": "",
            "document_type": "",
            "key_entities": []
        }
        try:
            print("Attempting Bedrock model extraction...")

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

    def extract_with_llm(self, text: str, company_bot=None, max_chars: int = 6000) -> Dict[str, Any]:
        """Extract structured information using AWS Bedrock Llama"""

        # Truncate if text is too long
        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        return self.extract_with_bedrock(document_text=text, company_bot=company_bot)

    def process_document(self, file_path: str) -> Dict[str, Any]:
        try:
            # Read document content
            text_content = self.read_document(file_path)

            if not text_content or len(text_content.strip()) < 10:
                raise ValueError("Document appears to be empty or unreadable")

            # Extract structured information using LLM
            extracted_info = self.extract_with_llm(text_content)

            # Add metadata (removed content_hash as requested)
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
def extract_tags_from_document_file(file, company_bot, file_extension: str) -> Dict[str, List[str]]:
    default_response = {
        "title": "",
        "organization": "",
        "tags": [],
        "exact_content": "",
        "summary": "",
        "document_type": "",
        "key_entities": []
    }
    try:
        extractor = DocumentExtractor()

        # Extract text from file
        document_text = extractor.extract_text_from_file(file, file_extension)

        if not document_text:
            return default_response

        # Extract information using Bedrock
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
