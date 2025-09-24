from chatbot.models import ChatStatus, CompanyChat
from chatbot.models.company_models import CompanyStateMachine
from chatbot.services.response_handlers.base_response_handler import BaseResponseHandler
from chatbot.utils.shiksha_chaupal.date_utils import handle_date_prompt
import logging
import json
from json_repair import repair_json

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
        messages = kwargs.get('messages')
        return temp_messages if temp_messages else messages

    def _analyze_response(self, response):
        """
        Analyze response to determine if it's a function call and extract content.
        """
        is_actual_function_call = self.is_function_call(response=response)

        if is_actual_function_call:
            return True, None, None

        extracted_response, reason_text = self._extract_response_and_reason(response)

        if extracted_response == '':
            print("DEBUG: Empty response detected after extraction, treating as function call for state transition")
            return True, extracted_response, reason_text

        return False, extracted_response, reason_text

    def analyze_response_for_postprocessing(self, response):
        """Override to handle empty responses as function calls for postprocessing"""
        is_function_call, _, _ = self._analyze_response(response)
        return is_function_call

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
            reason_text = None
            print("DEBUG: Skipping LLM call, treating as function call")
        else:
            # Use unified analysis - this handles everything including empty responses
            is_function_call, expected_output_response, reason_text = self._analyze_response(response)
            print(f"DEBUG: Analysis result - is_function_call: {is_function_call}")
            print(f"DEBUG: expected_output_response: '{expected_output_response}'")
            print(f"DEBUG: reason_text: '{reason_text}'")

        company_bot = kwargs['company_bot']
        session_id = kwargs['session_id']
        language = kwargs['language']
        profile_id = kwargs['profile_id']
        channel_name = kwargs['channel_name']
        skip_next_stage = kwargs.get('skip_next_stage', False)
        target_stage = kwargs.get('target_stage', False)
        chat_messages = self.get_messages_for_llm(**kwargs)

        # Process based on response type
        if is_function_call:
            print("DEBUG: Processing as function call")
            return self._handle_function_call(
                response=response, chat_session=chat_session, company_bot=company_bot,
                session_id=session_id, channel_name=channel_name, language=language, profile_id=profile_id,
                chunks=chunks, messages=chat_messages, skip_next_stage=skip_next_stage, target_stage=target_stage
            )
        else:
            print("DEBUG: Processing as regular response")
            # For non-function calls, use extracted response if available and not empty, otherwise original response
            final_response = expected_output_response if (
                    expected_output_response is not None and expected_output_response != "") else response
            return self._handle_regular_response(
                response=final_response, chat_session=chat_session, company_bot=company_bot,
                session_id=session_id, channel_name=channel_name, language=language, profile_id=profile_id,
                chunks=chunks, current_step=current_step, reason=reason_text
            )

    def _extract_response_and_reason(self, response):
        """Extract both response and reason from the response"""
        print(f"DEBUG: Extracting response and reason from response type: {type(response)}")
        print(f"DEBUG: Response content: {response}")

        try:
            # If response is a string, try to parse it as JSON
            if isinstance(response, str):
                print("DEBUG: Response is string, attempting JSON parsing with json_repair")
                try:
                    # First try regular json parsing
                    parsed_response = json.loads(response)
                except json.JSONDecodeError:
                    try:
                        # If that fails, try json_repair
                        repaired_json = repair_json(response)
                        parsed_response = json.loads(repaired_json)
                        print("DEBUG: Successfully repaired and parsed JSON")
                    except Exception as repair_error:
                        print(f"DEBUG: JSON repair failed: {repair_error}")
                        # If all parsing fails, use the string as response
                        return response, None

                response = parsed_response

            # If response is now a dict, extract parameters or input first
            if isinstance(response, dict):
                print("DEBUG: Response is dict, checking for parameters/input keys")

                # Pop parameters or input if they exist
                extracted_data = response.pop("parameters", response.pop("input", None))

                if extracted_data:
                    print("DEBUG: Found parameters/input, using extracted data")
                    response_data = extracted_data
                else:
                    print("DEBUG: No parameters/input found, using original response")
                    response_data = response

                # Now look for response and reason keys
                if isinstance(response_data, dict):
                    response_text = response_data.get('response', '')
                    reason_text = response_data.get('reason', '')

                    print(f"DEBUG: Extracted - response: '{response_text}', reason: '{reason_text}'")
                    return response_text, reason_text
                elif isinstance(response_data, str):
                    print("DEBUG: Response data is string, trying to parse as JSON")
                    try:
                        # Try to parse the string as JSON
                        parsed_data = json.loads(response_data)
                    except json.JSONDecodeError:
                        try:
                            # Try json_repair on the string
                            repaired_data = repair_json(response_data)
                            parsed_data = json.loads(repaired_data)
                            print("DEBUG: Successfully repaired string data")
                        except Exception as e:
                            print(f"DEBUG: Failed to parse string data: {e}")
                            return response_data, None

                    if isinstance(parsed_data, dict):
                        response_text = parsed_data.get('response', '')
                        reason_text = parsed_data.get('reason', '')
                        print(f"DEBUG: Parsed string data - response: '{response_text}', reason: '{reason_text}'")
                        return response_text, reason_text

        except Exception as e:
            print(f"DEBUG: Error extracting response and reason: {e}")
            logger.error(f"Error extracting response and reason: {e}")

        print("DEBUG: Fallback - returning original response as string")
        return str(response) if not isinstance(response, str) else response, None

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

        # Prepare other_params with the whole function call response
        other_params = {'function_call_response': response}
        print(f"DEBUG: Saving whole function call response in other_params: {response}")

        self.save_message(
            session_id=session_id, profile_id=profile_id, message=bot_question, chunks=chunks,
            status=chat_status, translated_message=translated_message, stage=state_machine.name,
            other_params=other_params
        )

        return response

    def _handle_regular_response(self, response, chat_session, company_bot,
                                 session_id, channel_name, language, profile_id,
                                 chunks, current_step, reason=None):
        """Handle regular response for guided guest"""
        state_machine = CompanyStateMachine.objects.get(
            company_bot=company_bot, step=chat_session.current_step
        )

        translated_message = self.translate_message(
            message=response, channel_name=channel_name, step_number=current_step,
            language=language, company_bot=company_bot
        )

        # Prepare other_params with reason if available
        other_params = {}
        if reason:
            other_params['reason'] = reason
            print(f"DEBUG: Adding reason to other_params: {reason}")

        self.save_message(
            session_id=session_id, profile_id=profile_id, message=response, chunks=chunks,
            status=ChatStatus.IN_PROGRESS, translated_message=translated_message, stage=state_machine.name,
            other_params=other_params if other_params else None
        )

        return response
