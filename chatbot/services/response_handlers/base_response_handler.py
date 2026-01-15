from abc import ABC, abstractmethod
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.celery_tasks.handle_message import translate_and_send_message
from chatbot.llm_models.llm_script import handle_bedrock_model, handle_openai_response_api
from chatbot.models import ChatSession, ChatStatus, LLMProvider, CompanyBotTypeChoices
import logging
from chatbot.models.company_models import CompanyStateMachine, CompanyChat
from chatbot.services.postprocessing.postprocessing_service import PostprocessingService
from chatbot.services.preprocessing.preprocessing_service import PreprocessingService

logger = logging.getLogger('django')
channel_layer = get_channel_layer()


class BaseResponseHandler(ABC):
    """Base class for handling LLM responses with common functionality"""

    def __init__(self):
        self.default_error_message = 'I am sorry, I could not understood completely. Could you rephrase this please?'
        self.preprocessing_service = PreprocessingService()
        self.postprocessing_service = PostprocessingService()

    def handle_response(self, **kwargs):
        """Main response handling method"""
        # Extract common parameters
        session_id = kwargs['session_id']
        chat_session = ChatSession.objects.get(session=session_id)
        chunks = []

        # Check for early return conditions (bot-specific)
        early_return = self.check_early_return(chat_session, **kwargs)
        if early_return is not None:
            if isinstance(early_return, str):
                return early_return
            elif isinstance(early_return, dict):
                if early_return.get('skip_llm', False):
                    kwargs['skip_llm'] = True
            else:
                return early_return

        company_bot = kwargs.get('company_bot')
        try:
            state_machine = CompanyStateMachine.objects.filter(
                company_bot=company_bot, step=chat_session.current_step
            ).first()
        except Exception as e:
            logger.error(f"Error getting state machine: {e}")
            state_machine = None

        response = None
        streaming_completed=False
        if not kwargs.get('skip_llm', False):
            result = self.get_llm_response(**kwargs)

            if isinstance(result, tuple):
                response, extra_content, finish_reason = result
            else:
                response = result
                finish_reason = None

            use_streaming = self.should_use_streaming(company_bot)

            streaming_completed = finish_reason == "stop" and use_streaming

            if response is None:
                if company_bot.bot_type == CompanyBotTypeChoices.STATE_MACHINE:
                    response = {
                        "toolUseId": "tooluse_fallback", "name": "get_state_information",
                        "input": {
                            "next_state_name": "SAMPLE",
                            "reason": "LLM returned no response"
                        }
                    }
                else:
                    response = self.default_error_message

        is_function_call = self.is_function_call(response=response) if state_machine else False
        if is_function_call and state_machine and response:
            postprocessing_result = self.postprocessing_service.execute_postprocessing(
                state_machine, response, **kwargs
            )

            # Handle postprocessing results
            if postprocessing_result.get('skip_next_stage', False):
                kwargs['skip_next_stage'] = True
                kwargs['target_stage'] = state_machine.skip_to_step
                logger.info("Postprocessing will skip next stage")

                next_stage_number = kwargs['target_stage']
                try:
                    next_state_machine = CompanyStateMachine.objects.get(
                        company_bot=company_bot, step=next_stage_number
                    )

                    next_stage_preprocessing_result = self.preprocessing_service.execute_preprocessing(
                        next_state_machine, kwargs.get('system_prompt', []), **kwargs
                    )

                    if next_stage_preprocessing_result['action'] == 'skip':
                        kwargs['skip_next_stage_preprocessing'] = True

                except CompanyStateMachine.DoesNotExist:
                    logger.error(f"Next state machine {next_stage_number} not found for preprocessing")
            else:
                next_stage_number = chat_session.current_step + 1
                try:
                    next_state_machine = CompanyStateMachine.objects.get(
                        company_bot=company_bot, step=next_stage_number
                    )

                    next_stage_preprocessing_result = self.preprocessing_service.execute_preprocessing(
                        next_state_machine, kwargs.get('system_prompt', []), **kwargs
                    )

                    if next_stage_preprocessing_result['action'] == 'skip':
                        kwargs['skip_next_stage_preprocessing'] = True

                except CompanyStateMachine.DoesNotExist:
                    logger.info(f"Next state machine {next_stage_number} not found, likely at end of flow")

        return self.process_response(
            response, chat_session, chunks, streaming_completed=streaming_completed, **kwargs
        )

    def analyze_response_for_postprocessing(self, response):
        """Analyze if response needs postprocessing - can be overridden by subclasses"""
        return self.is_function_call(response)

    def should_use_streaming(self, company_bot):
        """
        Determine if streaming should be used for this bot.
        """
        try:
            if hasattr(company_bot, 'stream'):
                return bool(company_bot.stream)

            return False

        except Exception as e:
            logger.error(f"Error determining streaming mode: {e}")
            return False

    def get_llm_response(self, **kwargs):
        """Get response from LLM provider"""
        company_bot = kwargs['company_bot']
        system_prompt = kwargs['system_prompt']
        response = None
        message_to_send = self.get_messages_for_llm(**kwargs)

        session_id = kwargs['session_id']
        profile_id = kwargs.get('profile_id')
        channel_name = kwargs['channel_name']
        chat_session = ChatSession.objects.get(session=session_id)
        state_machine = None
        try:
            state_machine = CompanyStateMachine.objects.get(
                company_bot=company_bot, step=chat_session.current_step
            )
        except Exception as e:
            logger.error(f"Error getting state machine for tools: {e}")

        tools = None
        has_state_machine_tool_context = (
                state_machine
                and hasattr(state_machine, 'tool_context')
                and state_machine.tool_context
                and state_machine.tool_context.strip()
        )

        has_company_bot_tool_context = (
                company_bot
                and hasattr(company_bot, 'tool_context')
                and company_bot.tool_context
                and company_bot.tool_context.strip()
        )

        if has_state_machine_tool_context or (
                company_bot.bot_type == CompanyBotTypeChoices.SIMPLE and has_company_bot_tool_context
        ):
            tool_context = (
                state_machine.tool_context.strip()
                if has_state_machine_tool_context
                else company_bot.tool_context.strip()
            )

            try:
                import json_repair
                tools = json_repair.repair_json(tool_context, return_objects=True)
                logger.info("Using state machine tool_context")
            except Exception as e:
                logger.error(f"Failed to parse state machine tool_context: {e}")
                tools = None

        if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
            try:
                response = handle_bedrock_model(
                    system_prompt=system_prompt,
                    messages=message_to_send,
                    model_name=company_bot.llm_model,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    company_bot=company_bot,
                    tools=tools
                )
            except Exception as e:
                logger.error(f"Bedrock Error: %s", e)
                response = None

        elif company_bot.provider == LLMProvider.OPENAI:
            use_streaming = self.should_use_streaming(company_bot)

            logger.info(f"Using OpenAI {'streaming' if use_streaming else 'non-streaming'} for session {session_id}")

            result = self._handle_openai_response(
                system_prompt=system_prompt,
                messages=message_to_send,
                company_bot=company_bot,
                channel_name=channel_name,
                session_id=session_id,
                profile_id=profile_id,
                stream=use_streaming
            )

            if result is None or (isinstance(result, tuple) and result[0] is None):
                # Error case
                logger.error("OpenAI response returned None - error occurred")
                response = None
            elif isinstance(result, tuple):
                response, extra_content, finish_reason = result

                if extra_content:
                    print("Setting extra_content to ", extra_content)
                    kwargs['llm_extra_content'] = extra_content

                return response, extra_content, finish_reason
            else:
                response = result
        return response, None, None

    def _handle_openai_response(self, system_prompt, messages, company_bot,
                                channel_name, session_id, profile_id, stream=False):
        """
        Handle OpenAI response using handle_openai_response_api.
        Works for both streaming and non-streaming modes.
        """
        final_extra_content = None

        try:
            logger.info(f"Processing free-flow for session {session_id}, channel {channel_name}")

            tools = None
            tool_choice = None
            try:
                import json_repair
                tool_context = json_repair.repair_json(company_bot.tool_context, return_objects=True)
                if tool_context:
                    tools = tool_context.get("tool")
                    tool_choice = tool_context.get("tool_choice", "auto")

                logger.info("Using state machine tool_context")
            except Exception as e:
                logger.error(f"Failed to parse state machine tool_context: {e}")

            accumulated_response = ""
            finish_reason = None

            for chunk_data in handle_openai_response_api(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_token=company_bot.max_token if company_bot.max_token else 2048,
                    temperature=company_bot.bot_temperature if company_bot.bot_temperature is not None else 0.0,
                    company_bot=company_bot,
                    top_p=company_bot.filter_score if company_bot.filter_score else None,
                    tool_choice=tool_choice,
                    tools=tools,
                    stream=stream
            ):
                content = chunk_data.get('content', '')
                finish_reason = chunk_data.get('finish_reason')
                error = chunk_data.get('error')
                extra_content = chunk_data.get('extra_content')

                if error:
                    logger.error(f'OpenAI error: {error}')
                    if stream:
                        self._send_error_chunk(channel_name, "Error processing your request")
                    return None

                if content:
                    accumulated_response += content

                if extra_content:
                    print("got extra_content: ", extra_content)
                    final_extra_content = extra_content

                print(f"Finish reason: {finish_reason}")


                if stream:
                    if content:
                        self._send_chunk(channel_name, content, None, None)

                    if finish_reason == "stop":
                        self._send_chunk(
                            channel_name,
                            "",
                            "stop",
                            final_extra_content
                        )
            if accumulated_response:
                save_in_company_db(
                    session_id=session_id,
                    profile_id=profile_id,
                    initiated_by='AI',
                    message=accumulated_response,
                    chunks=None,
                    status=ChatStatus.IN_PROGRESS,
                    stage=None
                )

                logger.info(f'Completed OpenAI response, length: {len(accumulated_response)} chars')

            return accumulated_response, final_extra_content, finish_reason

        except Exception as e:
            logger.error(f'Error in OpenAI response handling: {e}', exc_info=True)
            if stream:
                self._send_error_chunk(channel_name, "An error occurred processing your message")
            return None, None, None

    def _send_chunk(self, channel_name, content, finish_reason, extra_content=None):
        """Send a chunk via channel layer to the WebSocket."""
        try:
            message_data = {
                "type": "chat.message",
                "text": {
                    "msg": content,
                    "source": "bot",
                    "type": "chunk",
                    "finish_reason": finish_reason
                },
            }

            if extra_content:
                message_data["text"]["extra_content"] = extra_content

            async_to_sync(channel_layer.send)(channel_name, message_data)

        except Exception as e:
            logger.error(f"Failed to send chunk to channel {channel_name}: {e}", exc_info=True)

    def _send_error_chunk(self, channel_name, error_msg):
        """Send error message via channel layer to the WebSocket."""
        try:
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "chat.message",
                    "text": {
                        "msg": error_msg,
                        "source": "bot",
                        "type": "error",
                        "finish_reason": "error"
                    },
                },
            )
        except Exception as e:
            logger.error(f"Failed to send error to channel {channel_name}: {e}")

    def get_default_tools_config(self):
        """Get default tools configuration - fallback for when no tool_context is available"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_state_information",
                    "description": "Get the information of the state you want to be in.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "state_name": {
                                "type": "string",
                                "description": "Name of the next state provided in the context."
                            }
                        },
                        "required": ["state_name"]
                    }
                }
            }
        ]

    def get_tools_config(self):
        """Deprecated - use get_default_tools_config() or PromptBuilder.get_tools_from_state_machine()"""
        logger.info("get_tools_config() is deprecated, use get_default_tools_config() instead")
        return self.get_default_tools_config()

    def is_function_call(self, response):
        """Check if response is a function call"""
        if isinstance(response, dict):
            # Check for various function call formats

            # Format 1: Direct tool use format (OLD)
            # {'toolUseId': '...', 'name': 'get_state_information', 'input': {...}}
            if 'toolUseId' in response and 'name' in response:
                return response.get('name') == 'get_state_information'

            # Format 2: Simple function call format (NEW)
            # {'name': 'get_state_information', 'parameters': {...}}
            elif 'name' in response and 'parameters' in response:
                return response.get('name') == 'get_state_information'

            # Format 3: OpenAI function_call format
            # {'function_call': {'name': 'get_state_information', 'arguments': {...}}}
            elif 'function_call' in response:
                function_call = response.get('function_call', {})
                return function_call.get('name') == 'get_state_information'

            # Format 4: OpenAI tool_calls format
            # {'tool_calls': [{'function': {'name': 'get_state_information', ...}}]}
            elif 'tool_calls' in response:
                tool_calls = response.get('tool_calls', [])
                for tool_call in tool_calls:
                    if 'function' in tool_call:
                        function = tool_call.get('function', {})
                        if function.get('name') == 'get_state_information':
                            return True
                return False

            # Format 5: Bedrock response format
            # {'output': {'message': {'content': [{'toolUse': {'name': 'get_state_information', ...}}]}}}
            elif 'output' in response and 'message' in response.get('output', {}):
                content = response['output']['message'].get('content', [])
                for item in content:
                    if 'toolUse' in item:
                        tool_use = item.get('toolUse', {})
                        if tool_use.get('name') == 'get_state_information':
                            return True
                return False

            # Format 6: Just 'parameters' or 'input' without 'name' - check carefully
            elif 'parameters' in response or 'input' in response:
                # If it only has parameters/input but no clear function call indicators,
                # check if the nested data contains function call info
                nested_data = response.get('parameters') or response.get('input')
                if isinstance(nested_data, dict):
                    # Function calls have 'next_state_name' - this is the key differentiator
                    if 'next_state_name' in nested_data:
                        return True
                    # Regular responses have 'response' key - this indicates it's not a function call
                    elif 'response' in nested_data:
                        return False
                    # If neither, fall back to string search
                    else:
                        return 'get_state_information' in str(nested_data)
                # Check if 'get_state_information' appears in the nested data
                return 'get_state_information' in str(nested_data)

            # Format 7: Check if 'get_state_information' appears anywhere in the dict values
            # But be more restrictive - only if it appears as a function name, not in text
            elif any(key in response for key in ['toolUseId', 'tool_calls', 'function_call']):
                return 'get_state_information' in str(response)

            # If none of the above, it's likely a regular dict response (like {"response": "...", "reason": "..."})
            return False

        elif isinstance(response, str):
            return 'get_state_information' in response

        return False

    def save_message(self, session_id, profile_id, message, chunks,
                     status, translated_message, stage=None, other_params=None):
        """Save message to database"""
        save_in_company_db(
            session_id=session_id,
            profile_id=profile_id,
            initiated_by='AI',
            message=message,
            chunks=chunks,
            status=status,
            translated_message=translated_message,
            stage=stage,
            other_params=other_params
        )

    def translate_message(self, message, channel_name, step_number, language, company_bot, extra_content=None):
        """Translate and send message"""
        return translate_and_send_message(
            accumulated_message=message,
            current_channel_name=channel_name,
            current_step_number=step_number,
            finish_reason="stop",
            route=language,
            company_bot=company_bot,
            extra_content=extra_content
        )

    def get_chat_status(self, state_machine, company_bot):
        """Determine chat status based on state"""
        last_state = CompanyStateMachine.objects.filter(company_bot=company_bot).order_by('step').last()
        max_step = last_state.step if last_state else None

        if state_machine.step == max_step:
            return ChatStatus.COMPLETED
        else:
            return ChatStatus.IN_PROGRESS
        # return ChatStatus.COMPLETED if state_machine.name == "APPRECIATION" else ChatStatus.IN_PROGRESS

    # Abstract methods to be implemented by specific bot handlers
    @abstractmethod
    def check_early_return(self, chat_session, **kwargs):
        """Check if we should return early (bot-specific logic)"""
        pass

    @abstractmethod
    def get_messages_for_llm(self, **kwargs):
        """Get appropriate messages for LLM"""
        pass

    @abstractmethod
    def process_response(self, response, chat_session, chunks, **kwargs):
        """Process the LLM response (bot-specific logic)"""
        pass
