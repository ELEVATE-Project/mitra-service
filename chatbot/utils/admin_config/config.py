"""
Admin Configuration for Post Processing

This module defines all processing types and their configurations
for the admin post-processing interface.
"""

from enum import Enum
from typing import Dict, List, Any


# Common fields that all processing types share
COMMON_FIELDS = ['input_file', 'date_from', 'date_till']


class ProcessingType(Enum):
    """
    Enum for all available post-processing types.
    Each type has a value (used in form/URL) and associated configuration.
    """
    UNIQUE_CHALLENGES = 'unique_challenges'
    
    @property
    def label(self) -> str:
        """Human-readable label for the processing type"""
        return PROCESSING_TYPE_CONFIG[self]['label']
    
    @property
    def template_name(self) -> str:
        """Template file name for the processing type's form fields"""
        return PROCESSING_TYPE_CONFIG[self]['template_name']
    
    @property
    def fields(self) -> List[Dict[str, Any]]:
        """Configuration for form fields specific to this processing type"""
        return PROCESSING_TYPE_CONFIG[self]['fields']
    
    @property
    def handler_method(self) -> str:
        """Name of the method in PostProcessingView that handles this type"""
        return PROCESSING_TYPE_CONFIG[self]['handler_method']


# Configuration for each processing type
PROCESSING_TYPE_CONFIG: Dict[ProcessingType, Dict[str, Any]] = {
    ProcessingType.UNIQUE_CHALLENGES: {
        'label': 'Unique Challenges',
        'template_name': 'admin/post_processing/forms/unique_challenges_form.html',
        'handler_method': '_run_unique_challenges_processing',
        'fields': [
            {
                'name': 'max_workers',
                'type': 'number',
                'label': 'Max Workers',
                'default': 4,
                'min': 1,
                'max': 8,
                'help_text': 'How many parallel workers to use for processing.'
            },
            {
                'name': 'batch_size',
                'type': 'number',
                'label': 'Batch Size',
                'default': 100,
                'min': 1,
                'max': 1000,
                'help_text': 'How many challenges to process together in each batch.'
            },
            {
                'name': 'max_iterations',
                'type': 'number',
                'label': 'Max Iterations',
                'default': 10,
                'min': 1,
                'max': 50,
                'help_text': 'The system will keep filtering duplicates until this many rounds.'
            },
            {
                'name': 'filter_threshold',
                'type': 'number',
                'label': 'Filter Threshold (%)',
                'default': 10,
                'min': 1,
                'max': 100,
                'step': 0.1,
                'help_text': 'Stop processing when filtering is lower than this percentage. Lower percentage means aggressive filtering.'
            },
        ]
    },
}


def get_all_processing_types() -> List[Dict[str, str]]:
    return [
        {
            'value': ptype.value,
            'label': ptype.label
        }
        for ptype in ProcessingType
    ]


def get_processing_type_by_value(value: str) -> ProcessingType:
    for ptype in ProcessingType:
        if ptype.value == value:
            return ptype
    return None


def get_processing_type_config(processing_type: ProcessingType) -> Dict[str, Any]:
    return PROCESSING_TYPE_CONFIG.get(processing_type, {})
