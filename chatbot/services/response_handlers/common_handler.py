from chatbot.models import ChatStatus, CompanyChat
from chatbot.models.company_models import CompanyStateMachine
from chatbot.services.response_handlers.base_response_handler import BaseResponseHandler
from chatbot.utils.shiksha_chaupal.date_utils import handle_date_prompt
import logging

logger = logging.getLogger('django')


class CommonResponseHandler(BaseResponseHandler):
    """Common Response handler for bot"""

    def check_early_return(self, chat_session, **kwargs):
        """Check for EVENT state early return"""
        company_bot = kwargs['company_bot']

        try:
            state_machine = CompanyStateMachine.objects.get(
                company_bot=company_bot, step=chat_session.current_step
            )
            print("Current step in early func: ", state_machine.name)
            # Special handling for EVENT state
            if state_machine and state_machine.name == 'EVENT_DATE':
                print("Here inside")
                return self._handle_event_state(chat_session=chat_session, state_machine=state_machine, **kwargs)
        except Exception as e:
            print("Error: ", e)
            logger.error(f"Error in check_early_return: {e}")

        return None

    def _handle_event_state(self, chat_session, state_machine, **kwargs):
        """Handle EVENT state with date prompt"""
        intro_mssg = kwargs.get('intro_mssg')
        profile = kwargs.get('profile')
        other_info = kwargs.get('other_info')
        channel_name = kwargs['channel_name']
        language = kwargs['language']
        company_bot = kwargs['company_bot']
        session_id = kwargs['session_id']
        profile_id = kwargs['profile_id']
        print("Before date fun")
        company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
        bot_question = handle_date_prompt(
            intro_mssg=intro_mssg,
            profile=profile,
            company_chats=company_chats,
            other_info=other_info
        )
        print("DATE RES: ", bot_question)
        if bot_question is None:
            bot_question = self.default_error_message

        if bot_question == '':
            # Return special flag to skip LLM call
            return {'skip_llm': True}
        else:
            # Send the date prompt response
            translated_message = self.translate_message(
                message=bot_question, channel_name=channel_name, step_number=chat_session.current_step,
                language=language, company_bot=company_bot
            )

            self.save_message(
                session_id=session_id, profile_id=profile_id, message=bot_question, chunks=None,
                status=ChatStatus.IN_PROGRESS, translated_message=translated_message, stage=state_machine.name
            )

            return bot_question

    def get_messages_for_llm(self, **kwargs):
        """Use temp_messages if available, otherwise original messages"""
        temp_messages = kwargs.get('temp_messages')
        messages=kwargs.get('messages')
        return temp_messages if temp_messages else messages

    def process_response(self, response, chat_session, chunks, **kwargs):
        """Process common response"""
        print(f"DEBUG: Starting process_response with response type: {type(response)}")
        print(f"DEBUG: Response preview: {str(response)[:200]}...")

        skip_llm_call = kwargs.get('skip_llm', False)
        print(f"DEBUG: skip_llm_call: {skip_llm_call}")

        current_step = chat_session.current_step
        if skip_llm_call:
            is_function_call = True
            expected_output_response = None
            print("DEBUG: Skipping LLM call, treating as function call")
        else:
            is_function_call = self.is_function_call(response=response)
            print(f"DEBUG: is_function_call: {is_function_call}")

            expected_output_response = self._extract_expected_output(response)
            print(f"DEBUG: expected_output_response: '{expected_output_response}'")

        company_bot = kwargs['company_bot']
        session_id = kwargs['session_id']
        language = kwargs['language']
        profile_id = kwargs['profile_id']
        channel_name = kwargs['channel_name']
        skip_next_stage = kwargs.get('skip_next_stage', False)
        target_stage = kwargs.get('target_stage', False)
        chat_messages = self.get_messages_for_llm(**kwargs)

        # Check if we have expected_output and should treat as regular response
        if is_function_call and expected_output_response:
            print(
                f"DEBUG: Function call has expected_output: '{expected_output_response}'. Treating as regular response.")
            logger.info(f"Function call has expected_output: {expected_output_response}. Treating as regular response.")
            return self._handle_regular_response(
                response=expected_output_response, chat_session=chat_session, company_bot=company_bot,
                session_id=session_id, channel_name=channel_name, language=language, profile_id=profile_id,
                chunks=chunks, current_step=current_step
            )
        elif is_function_call:
            print("DEBUG: Processing as function call (no expected_output or empty expected_output)")
            return self._handle_function_call(
                response=response, chat_session=chat_session, company_bot=company_bot,
                session_id=session_id, channel_name=channel_name, language=language, profile_id=profile_id,
                chunks=chunks, messages=chat_messages, skip_next_stage=skip_next_stage, target_stage=target_stage
            )
        else:
            print("DEBUG: Processing as regular response")
            return self._handle_regular_response(
                response=response, chat_session=chat_session, company_bot=company_bot,
                session_id=session_id, channel_name=channel_name, language=language, profile_id=profile_id,
                chunks=chunks, current_step=current_step
            )

    def _extract_expected_output(self, response):
        """Extract expected_output from function call response if it exists and is not empty"""
        print(f"DEBUG: Extracting expected_output from response type: {type(response)}")
        print(f"DEBUG: Response content: {response}")

        def _extract_and_return(expected_output, format_name):
            """Helper to extract and return expected_output if not empty"""
            print(f"DEBUG: Expected output from {format_name}: '{expected_output}'")
            return expected_output if expected_output else None

        def _parse_json_string(json_str):
            """Helper to safely parse JSON string"""
            try:
                import json
                return json.loads(json_str)
            except json.JSONDecodeError:
                return None

        try:
            if isinstance(response, dict):
                # Handle simple function call format (NEW format)
                if 'name' in response and 'parameters' in response:
                    print("DEBUG: Found simple function call format (NEW)")
                    expected_output = response['parameters'].get('expected_output', '')
                    return _extract_and_return(expected_output, "simple function call")

                # Handle direct tool use format (OLD format)
                elif 'toolUseId' in response and 'input' in response:
                    print("DEBUG: Found direct tool use format (OLD)")
                    expected_output = response['input'].get('expected_output', '')
                    return _extract_and_return(expected_output, "direct tool use")

                # Handle Bedrock response format
                elif 'output' in response and 'message' in response['output']:
                    print("DEBUG: Found Bedrock response format")
                    content = response['output']['message'].get('content', [])
                    for item in content:
                        if 'toolUse' in item:
                            expected_output = item['toolUse'].get('input', {}).get('expected_output', '')
                            return _extract_and_return(expected_output, "Bedrock format")

                # Handle OpenAI-style function call formats
                elif 'function_call' in response or 'tool_calls' in response:
                    print("DEBUG: Found OpenAI-style function call format")

                    # Handle tool_calls format
                    if 'tool_calls' in response:
                        for tool_call in response['tool_calls']:
                            if 'function' in tool_call:
                                arguments = tool_call['function'].get('arguments', {})
                                if isinstance(arguments, str):
                                    arguments = _parse_json_string(arguments)
                                if arguments:
                                    expected_output = arguments.get('expected_output', '')
                                    return _extract_and_return(expected_output, "OpenAI tool_calls")

                    # Handle function_call format
                    elif 'function_call' in response:
                        arguments = response['function_call'].get('arguments', {})
                        if isinstance(arguments, str):
                            arguments = _parse_json_string(arguments)
                        if arguments:
                            expected_output = arguments.get('expected_output', '')
                            return _extract_and_return(expected_output, "OpenAI function_call")

            elif isinstance(response, str):
                print("DEBUG: Found string response, trying to parse JSON")
                # Look for function call patterns in string
                if 'get_state_information' in response:
                    import re
                    # Try to extract JSON from the string
                    json_match = re.search(r'\{.*\}', response, re.DOTALL)
                    if json_match:
                        parsed = _parse_json_string(json_match.group())
                        if parsed:
                            expected_output = parsed.get('expected_output', '')
                            return _extract_and_return(expected_output, "string parsing")

        except Exception as e:
            print(f"DEBUG: Error extracting expected_output: {e}")
            logger.error(f"Error extracting expected_output: {e}")

        print("DEBUG: No expected_output found, returning None")
        return None


    def _handle_function_call(self, response, chat_session, company_bot,
                              session_id, channel_name, language, profile_id, chunks, messages, skip_next_stage,
                              target_stage):
        """Handle function call for guided guest"""
        if skip_next_stage:
            if target_stage and isinstance(target_stage, int):
                chat_session.current_step = target_stage
            else:
                chat_session.current_step += 2
        else:
            chat_session.current_step += 1
        chat_session.save()

        state_machine = CompanyStateMachine.objects.get(
            company_bot=company_bot, step=chat_session.current_step
        )
        bot_question = state_machine.bot_question

        chat_status = self.get_chat_status(state_machine=state_machine, company_bot=company_bot)

        translated_message = self.translate_message(
            message=bot_question, channel_name=channel_name, step_number=chat_session.current_step,
            language=language, company_bot=company_bot
        )

        self.save_message(
            session_id=session_id, profile_id=profile_id, message=bot_question, chunks=chunks,
            status=chat_status, translated_message=translated_message, stage=state_machine.name
        )

        return response

    def _handle_regular_response(self, response, chat_session, company_bot,
                                 session_id, channel_name, language, profile_id,
                                 chunks, current_step):
        """Handle regular response for guided guest"""
        state_machine = CompanyStateMachine.objects.get(
            company_bot=company_bot, step=chat_session.current_step
        )

        translated_message = self.translate_message(
            message=response, channel_name=channel_name, step_number=current_step,
            language=language, company_bot=company_bot
        )

        self.save_message(
            session_id=session_id, profile_id=profile_id, message=response, chunks=chunks,
            status=ChatStatus.IN_PROGRESS, translated_message=translated_message, stage=state_machine.name
        )

        return response
