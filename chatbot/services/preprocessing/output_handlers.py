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
        logger.info(f"[SkipOutputHandler] Handling SKIP mode.")
        logger.info(f"[SkipOutputHandler] preprocess_response type: {type(preprocess_response)}")
        logger.info(f"[SkipOutputHandler] preprocess_response: {preprocess_response}")

        if not preprocess_response:
            logger.info("[SkipOutputHandler] No preprocess_response provided. Continue to next stage.")
            return {'action': 'continue'}

        should_skip = False

        if isinstance(preprocess_response, dict):
            logger.info("[SkipOutputHandler] preprocess_response is already a dict.")
            parsed = preprocess_response
        else:
            try:
                parsed = json_repair.repair_json(preprocess_response, return_objects=True)
                logger.info(f"[SkipOutputHandler] Parsed JSON successfully: {parsed}")
            except json.JSONDecodeError:
                logger.error("[SkipOutputHandler] Failed to parse JSON. Using fallback text mode.")
                parsed = None

        if isinstance(parsed, dict):
            for key, val in parsed.items():
                logger.info(f"[SkipOutputHandler] Checking key='{key}', value={val}")
                key_lower = str(key).lower()
                if any(skip_word in key_lower for skip_word in ["reason", "reasoning", "explanation"]):
                    logger.info(f"[SkipOutputHandler] Skipping check for key '{key}' (reasoning/explanation).")
                    continue

                if isinstance(val, bool):
                    logger.info(f"[SkipOutputHandler] Boolean value detected: {val}")
                    if val:
                        logger.info(f"[SkipOutputHandler] Skip triggered by boolean True in key '{key}'.")
                        should_skip = True
                        break
                elif isinstance(val, str):
                    val_stripped = val.strip().lower()
                    logger.info(f"[SkipOutputHandler] String value detected: '{val_stripped}'")
                    if val_stripped in ["yes", "true", "skip"]:
                        should_skip = True
                        logger.info(f"[SkipOutputHandler] Skip triggered by string '{val_stripped}' in key '{key}'.")
                        break

        else:
            text = str(preprocess_response).strip().lower()
            logger.info(f"[SkipOutputHandler] Fallback text mode. Processed text: '{text}'")
            if text in ["skip", "yes", "true"]:
                should_skip = True
                logger.info(f"[SkipOutputHandler] Skip triggered by fallback text '{text}'.")

        logger.info(f"[SkipOutputHandler] Final decision: skip={should_skip}")

        if should_skip:
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
