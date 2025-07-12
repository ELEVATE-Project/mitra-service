import json
from chatbot.models import PostProcessOutputMode
import json_repair
import logging

logger = logging.getLogger('django')


class PostprocessOutputHandler:
    """Handles different postprocessing output modes"""

    @staticmethod
    def handle_output(output_mode, postprocess_response, llm_response, **kwargs):
        """Handle postprocessing output based on mode"""
        if output_mode == PostProcessOutputMode.SKIP:
            return PostprocessSkipOutputHandler.handle(postprocess_response, llm_response, **kwargs)
        else:
            return {'action': 'continue', 'skip_next_stage': False}


class PostprocessSkipOutputHandler:
    """Handles SKIP output mode for postprocessing"""

    @staticmethod
    def handle(postprocess_response, llm_response, **kwargs):
        """
        Determine if we should skip the next stage based on postprocess response.
        :param postprocess_response: Raw string or dict-like response from LLM.
        :param llm_response: Original LLM raw response for fallback.
        :return: Dict with skip flag.
        """
        if not postprocess_response:
            return {'action': 'continue', 'skip_next_stage': False}
        if isinstance(postprocess_response, dict):
            values_to_check = list(postprocess_response.values())
        else:
            try:
                parsed = json_repair.repair_json(postprocess_response, return_objects=True)
                if isinstance(parsed, dict):
                    values_to_check = list(parsed.values())
                elif isinstance(parsed, list):
                    values_to_check = parsed
                else:
                    values_to_check = [str(parsed)]
            except json.JSONDecodeError:
                values_to_check = [str(postprocess_response)]
        should_skip = False
        for val in values_to_check:
            val_str = str(val).lower()
            if any(keyword in val_str for keyword in ['skip', 'yes', 'true']):
                should_skip = True
                logger.info(f"Postprocessing determined to skip next stage based on value: {val}")
                break

        return {'action': 'continue', 'skip_next_stage': should_skip}
