import json
import json_repair
from chatbot.models import PreProcessOutputMode, LLMProvider
import logging

logger = logging.getLogger('django')


class PreprocessOutputHandler:
    """Handles different preprocessing output modes"""

    @staticmethod
    def handle_output(output_mode, preprocess_response, original_prompt, **kwargs):
        """Handle preprocessing output based on mode"""
        if output_mode == PreProcessOutputMode.SKIP:
            return SkipOutputHandler.handle(preprocess_response, **kwargs)
        elif output_mode == PreProcessOutputMode.ENRICH:
            return EnrichOutputHandler.handle(preprocess_response, original_prompt, **kwargs)
        elif output_mode == PreProcessOutputMode.CUSTOM:
            return CustomOutputHandler.handle(preprocess_response, **kwargs)
        else:
            return {'action': 'continue', 'prompt': original_prompt}


class SkipOutputHandler:
    """Handles SKIP output mode"""

    @staticmethod
    def handle(preprocess_response, **kwargs):
        """
        Determine if we should skip the next stage based on preprocess response.
        :param preprocess_response: Raw string or dict-like response from LLM.
        :return: Dict with skip flag.
        """
        if not preprocess_response:
            return {'action': 'continue'}
        if isinstance(preprocess_response, dict):
            values_to_check = list(preprocess_response.values())
        else:
            try:
                parsed = json_repair.repair_json(preprocess_response, return_objects=True)
                if isinstance(parsed, dict):
                    values_to_check = list(parsed.values())
                elif isinstance(parsed, list):
                    values_to_check = parsed
                else:
                    values_to_check = [str(parsed)]
            except json.JSONDecodeError:
                values_to_check = [str(preprocess_response)]
        should_skip = False
        for val in values_to_check:
            val_str = str(val).lower()
            if any(keyword in val_str for keyword in ['skip', 'yes', 'true']):
                should_skip = True
                logger.info(f"Preprocessing determined to skip stage based on response: {preprocess_response}")
                break

        if should_skip:
            logger.info(f"Preprocessing determined to skip stage based on response: {preprocess_response}")
            return {'action': 'skip'}
        else:
            return {'action': 'continue'}


class EnrichOutputHandler:
    """Handles ENRICH output mode"""

    @staticmethod
    def handle(preprocess_response, original_prompt, **kwargs):
        """Enrich the original prompt with preprocessing output"""
        if not preprocess_response:
            return {'action': 'continue', 'prompt': original_prompt}

        company_bot = kwargs.get('company_bot')

        # Enrich prompt based on provider type
        if company_bot and hasattr(company_bot, 'provider'):
            if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
                enriched_prompt = original_prompt.copy()
                enriched_prompt.append({
                    'text': f"\nAdditional Context from Preprocessing:\n{preprocess_response}"
                })
            else:  # OpenAI
                if original_prompt and len(original_prompt) > 0:
                    original_content = original_prompt[0].get('content', '')
                    enriched_content = f"{original_content}\n\nAdditional Context from Preprocessing:\n{preprocess_response}"
                    enriched_prompt = [{'role': 'system', 'content': enriched_content}]
                else:
                    enriched_prompt = original_prompt
        else:
            enriched_prompt = original_prompt

        logger.info(f"Prompt enriched with preprocessing output: {preprocess_response}")
        return {'action': 'continue', 'prompt': enriched_prompt}


class CustomOutputHandler:
    """Handles CUSTOM output mode"""

    @staticmethod
    def handle(preprocess_response, **kwargs):
        """Handle custom preprocessing logic"""
        logger.info(f"Custom preprocessing logic called with response: {preprocess_response}")
        print(f"CUSTOM PREPROCESSING: {preprocess_response}")

        # For now, just print and continue with original flow
        # In the future, this can be extended to call specific custom functions
        return {'action': 'continue'}
