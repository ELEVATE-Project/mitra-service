"""
Service for exporting I18n translations to JSON format.
Prepares translations data for S3 upload.
"""
import json
from typing import Dict, Any, List, Tuple
from chatbot.models import I18nTag, I18nTranslation


# Predefined list of supported languages
SUPPORTED_LANGUAGES: List[Tuple[str, str]] = [
    ('en', 'English'),
    ('hi', 'Hindi'),
    ('kn', 'Kannada'),
    ('te', 'Telugu'),
]


def get_supported_languages() -> List[Tuple[str, str]]:
    """
    Returns the list of supported languages for i18n export.
    
    Returns:
        List of tuples containing (language_code, language_name)
    """
    return SUPPORTED_LANGUAGES


def generate_i18n_json_for_language(language: str) -> Dict[str, Dict[str, Any]]:
    """
    Generate JSON structure for all i18n tags and translations for a given language.
    
    Args:
        language: Language code (e.g., 'en', 'hi', 'kn')
    
    Returns:
        Dictionary structured as:
        {
            "tag_name": {
                "variable_name": "translated_value",
                ...
            },
            ...
        }
    """
    result: Dict[str, Dict[str, Any]] = {}

    tags = I18nTag.objects.all().order_by('tag_name')
    
    for tag in tags:
        tag_translations = {}
        
        # Fetch all translations for this tag in the specified language
        translations = I18nTranslation.objects.filter(
            tag_id=tag,
            language=language.lower()
        ).order_by('variable_name')
        
        for translation in translations:
            tag_translations[translation.variable_name] = translation.value
        
        # Only add tag to result if it has translations for this language
        if tag_translations:
            result[tag.tag_name] = tag_translations
    
    return result


def get_export_filename(language: str) -> str:
    """
    Generate the filename for the export JSON file.
    Following the S3 naming convention: translations/{language}/translations.json
    
    Args:
        language: Language code (e.g., 'en', 'hi')
    
    Returns:
        Filename string (e.g., 'translations_en.json')
    """
    return f"translations_{language}.json"


def get_s3_path(language: str) -> str:
    """
    Generate the S3 path for the translations file.
    
    Args:
        language: Language code (e.g., 'en', 'hi')
    
    Returns:
        S3 path string (e.g., 'translations/en/translations.json')
    """
    return f"translations/{language}/translations.json"


def generate_i18n_json_string(language: str, indent: int = 2) -> str:
    """
    Generate JSON string for all i18n translations in a given language.
    
    Args:
        language: Language code (e.g., 'en', 'hi')
        indent: JSON indentation level (default: 2)
    
    Returns:
        JSON string representation of the translations
    """
    data = generate_i18n_json_for_language(language)
    return json.dumps(data, ensure_ascii=False, indent=indent)
