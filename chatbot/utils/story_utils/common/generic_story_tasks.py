import logging
import json
import re
from chatbot.models import StoryStatusChoices, Story, Voice, VoiceType, StoryTranslation
from chatbot.models.geo_models import ProfileAddress
from chatbot.models.story_vernacular_model import StoryVernacular
from chatbot.utils.story_llama_utils import translate_field
from chatbot.utils.story_utils.format_utils import clean_escaped_text, get_formatted_story
from chatbot.utils.transliterate_utils import transliterate_text, get_transliteration_output

logger = logging.getLogger('django')


def is_english_text(text):
    """Check if text contains only English characters (a-z, A-Z, numbers, punctuation, spaces)"""
    if not text or text.strip() == '':
        return True

    # Remove common punctuation and numbers
    cleaned_text = re.sub(r'[0-9\s\.,\!\?\-\(\)\[\]\{\}\"\'\:\;\@\#\$\%\^\&\*\+\=\_\|\\\/<>~`]', '', str(text))

    # Check if remaining characters are only English letters
    return bool(re.match(r'^[a-zA-Z]*$', cleaned_text))


def translate_to_english_if_needed(text, voice_provider, source_language):
    """Translate text to English if it's not already in English"""
    if not text or text.strip() == '':
        return text

    if is_english_text(text):
        return text

    try:
        if voice_provider:
            translated = translate_field(
                voice_provider=voice_provider,
                message_body=text,
                target_language='en',
                source_language=source_language

            )
            return translated
        else:
            logger.info(f"No voice provider available for translation. Keeping original text: {text}")
            return text
    except Exception as e:
        logger.error(f"Error translating to English: {e}")
        return text


def transliterate_to_english_if_needed(text, voice_provider, source_language):
    """Transliterate text to English if it's not already in English"""
    logger.info(f"Starting Transliteration for {text}.")
    if not text or text.strip() == '':
        logger.info(f"Text is empty or null so return original text.")
        return text

    if is_english_text(text):
        logger.info(f"Text is english so return so return original text.")
        return text

    try:
        if voice_provider:
            is_sentence = ' ' in text
            logger.info(f"STARTED TRANSLITERATION.")
            transliterated = transliterate_text(
                voice_provider=voice_provider,
                message_body=text,
                target_language='en',
                source_language=source_language,
                is_sentence=is_sentence
            )
            return get_transliteration_output(data=transliterated)
        else:
            logger.info(f"No voice provider available for transliteration. Keeping original text: {text}")
            return text
    except Exception as e:
        logger.error(f"Error transliterating to English: {e}")
        return text


def translate_nested_to_english(data, voice_provider, transliteration_voice_provider, source_language, field_path=""):
    """Recursively translate nested data structures to English"""
    if isinstance(data, dict):
        translated_dict = {}
        for key, value in data.items():
            current_path = f"{field_path}.{key}" if field_path else key
            logger.info(f"DEBUG: Processing {key} = '{value}' (type: {type(value)})")

            if isinstance(value, str) and value.strip():
                # Determine if this should be translated or transliterated
                personal_info_fields = ['name', 'user_name', 'location', 'organization', 'designation', 'district',
                                        'block']
                if key.lower() in personal_info_fields or any(field in key.lower() for field in personal_info_fields):
                    # Transliterate personal info
                    translated_dict[key] = transliterate_to_english_if_needed(value, transliteration_voice_provider,
                                                                              source_language)
                else:
                    # Translate content
                    translated_dict[key] = translate_to_english_if_needed(value, voice_provider, source_language)
            elif isinstance(value, (dict, list)):
                # Recursively handle nested structures
                translated_dict[key] = translate_nested_to_english(value, voice_provider,
                                                                   transliteration_voice_provider, source_language,
                                                                   current_path)
            else:
                # Keep non-text values as-is
                translated_dict[key] = value
        return translated_dict
    elif isinstance(data, list):
        translated_list = []
        for i, item in enumerate(data):
            if isinstance(item, str) and item.strip():
                # For list items, default to translation (most arrays contain content, not personal info)
                translated_list.append(translate_to_english_if_needed(item, voice_provider, source_language))
            elif isinstance(item, (dict, list)):
                translated_list.append(
                    translate_nested_to_english(item, voice_provider, transliteration_voice_provider, source_language,
                                                f"{field_path}[{i}]"))
            else:
                translated_list.append(item)
        return translated_list
    else:
        return data


def save_generic_story(
        response_json_story, language, voice_provider, profile, session, combined_reason, flow=None, project_id=None,
        company_bot=None
):
    """
    Generic save story function that saves English content to Story model
    and creates translations for other languages.
    Now detects and converts non-English content to English before saving.
    """
    # Get voice providers for translation/transliteration
    translation_voice_provider = voice_provider
    transliteration_voice_provider = None

    if company_bot and language != 'en':
        transliteration_voice_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.Transliterate, language=language
        ).first()

    # Validate that response_json_story is valid JSON
    if isinstance(response_json_story, str):
        try:
            response_json_story = json.loads(response_json_story)
        except json.JSONDecodeError:
            raise Exception("Invalid JSON response from story generation")

    # Ensure response_json_story is a dictionary
    if not isinstance(response_json_story, dict):
        raise Exception("Response must be a valid JSON object")

    print("For saving response_json_story: ", response_json_story)

    # Parse JSON strings within the response
    def parse_json_strings(data):
        """Parse JSON strings that are arrays [] or objects {} within the data"""
        if isinstance(data, dict):
            parsed_data = {}
            for key, value in data.items():
                if isinstance(value, str) and value.strip():
                    stripped_value = value.strip()
                    if ((stripped_value.startswith('[') and stripped_value.endswith(']')) or
                            (stripped_value.startswith('{') and stripped_value.endswith('}'))):
                        try:
                            parsed_data[key] = json.loads(stripped_value)
                        except json.JSONDecodeError:
                            parsed_data[key] = value
                    else:
                        parsed_data[key] = value
                else:
                    parsed_data[key] = parse_json_strings(value) if isinstance(value, (dict, list)) else value
            return parsed_data
        elif isinstance(data, list):
            return [parse_json_strings(item) for item in data]
        else:
            return data

    # Parse any JSON strings in the response
    response_json_story = parse_json_strings(response_json_story)

    # Translate main content fields to English
    raw_title = response_json_story.get('title', '')
    raw_content = response_json_story.get('content', '')
    raw_objective = response_json_story.get('objective', '')
    raw_impact = response_json_story.get('impact', '')
    raw_blurb = response_json_story.get('blurb', '')

    english_title = clean_escaped_text(
        text=translate_to_english_if_needed(raw_title, translation_voice_provider, language)
    )
    english_content = clean_escaped_text(
        text=translate_to_english_if_needed(raw_content, translation_voice_provider, language)
    )
    english_objective = clean_escaped_text(
        text=translate_to_english_if_needed(raw_objective, translation_voice_provider, language)
    )
    english_impact = clean_escaped_text(
        text=translate_to_english_if_needed(raw_impact, translation_voice_provider, language)
    )
    english_blurb = clean_escaped_text(
        text=translate_to_english_if_needed(raw_blurb, translation_voice_provider, language)
    )

    # Handle fields that typically don't need translation
    english_tweet = response_json_story.get('tweet', '')
    english_micro_improvement = response_json_story.get('micro_improvement', '')

    # Handle action_steps (can be string or list)
    raw_action_steps = response_json_story.get('action_steps', [])
    if isinstance(raw_action_steps, str):
        english_action_steps = translate_to_english_if_needed(raw_action_steps, translation_voice_provider, language)
    elif isinstance(raw_action_steps, list):
        english_action_steps = [
            translate_to_english_if_needed(step, translation_voice_provider, language)
            for step in raw_action_steps
        ]
    else:
        english_action_steps = raw_action_steps

    # Get title from StoryVernacular if not present
    if not english_title and company_bot:
        try:
            story_vernacular = StoryVernacular.objects.filter(
                company_bot=company_bot, language='en'  # Get English vernacular
            ).first()

            if story_vernacular and story_vernacular.translation_json:
                vernacular_title = story_vernacular.translation_json.get('title')
                if vernacular_title:
                    english_title = vernacular_title
                    logger.info(f"Used StoryVernacular English title")
        except Exception as e:
            logger.info(f"Could not get title from StoryVernacular: {e}")

    if not english_title or not english_title.strip():
        english_title = 'Improvement_story'
        logger.info("Using default title: Improvement_story")

    # Get basic profile information
    user_name = profile.first_name if profile and profile.first_name else ''
    fallback_location = ""
    if profile:
        address = ProfileAddress.objects.filter(profile=profile).first()
        if address:
            location_parts = filter(None, [address.block, address.district, address.state])
            fallback_location = ", ".join(location_parts)

    # Process other fields that don't need translation
    other_params = {
        'flow': flow,
        'user_name': user_name,
    }

    # Define Story model fields that map directly
    STORY_MODEL_FIELDS = {
        'title', 'content', 'tweet', 'objective', 'action_steps',
        'impact', 'micro_improvement', 'blurb', 'language', 'stage',
        'other_params', 'location', 'validation_logs'
    }

    # Define fields that should never be translated
    NON_TRANSLATABLE_FIELDS = {'flow', 'id', 'uuid', 'status', 'type', 'mode', 'version'}

    # Define personal info fields that need transliteration
    PERSONAL_INFO_FIELDS = {'name', 'user_name', 'location', 'organization', 'designation', 'district', 'block'}

    # Add ALL other fields from JSON to other_params, translating them appropriately
    for key, value in response_json_story.items():
        if key not in STORY_MODEL_FIELDS:
            if isinstance(value, dict) or isinstance(value, list):
                # Handle complex nested structures (like question_answers)
                other_params[key] = translate_nested_to_english(
                    value, translation_voice_provider, transliteration_voice_provider, language, key
                )
            elif isinstance(value, str) and value.strip():
                # Handle simple string values
                if key.lower() in NON_TRANSLATABLE_FIELDS:
                    # Keep technical fields as-is
                    other_params[key] = value
                elif key.lower() in PERSONAL_INFO_FIELDS:
                    # Transliterate personal info fields
                    other_params[key] = transliterate_to_english_if_needed(value, transliteration_voice_provider,
                                                                           language)
                else:
                    # Translate content fields
                    other_params[key] = translate_to_english_if_needed(value, translation_voice_provider, language)
            else:
                # Keep non-string values as-is
                other_params[key] = value

    print(f"Story other_params before save: {other_params}")

    # Use fallback location if not provided, and translate if needed
    raw_location = response_json_story.get('location', fallback_location)
    location = ""
    if raw_location and raw_location.strip():
        location = transliterate_to_english_if_needed(raw_location, transliteration_voice_provider, language)

    # Prepare Story model fields (all in English)
    story_fields = {
        'title': english_title,
        'content': english_content,
        'tweet': english_tweet,
        'objective': english_objective,
        'action_steps': english_action_steps,
        'impact': english_impact,
        'micro_improvement': english_micro_improvement,
        'blurb': english_blurb,
        'location': location,
        'author': profile,
        'session': session,
        'language': 'en',  # Always English in Story model
        'stage': StoryStatusChoices.COMPLETED,
        'other_params': other_params,
        'validation_logs': combined_reason
    }

    # Check if story already exists for this session
    story = Story.objects.filter(session=session).first()
    if story:
        # Update existing story with English content
        for field, value in story_fields.items():
            if hasattr(story, field):
                setattr(story, field, value)
    else:
        # Create new story with English content
        story = Story(**story_fields)

    story.save()
    print(f"Story saved with other_params: {story.other_params}")

    # Create translation if language is not English
    if language != 'en':
        create_generic_story_translation(
            story=story,
            language=language,
            english_data={
                'title': english_title,
                'content': english_content,
                'tweet': english_tweet,
                'objective': english_objective,
                'action_steps': english_action_steps,
                'impact': english_impact,
                'micro_improvement': english_micro_improvement,
                'blurb': english_blurb
            },
            voice_provider=voice_provider,
            flow=flow,
            company_bot=company_bot,
            response_json_story=response_json_story  # Pass entire JSON instead of selected fields
        )

    logger.info(f"Successfully saved generic story for flow {flow}, session {session}")
    # Return problem_statement from JSON if it exists, translating to English
    raw_problem_statement = response_json_story.get('problem_statement', '')
    problem_statement = clean_escaped_text(
        text=translate_to_english_if_needed(raw_problem_statement, translation_voice_provider, language)
    )
    return story, problem_statement


def create_generic_story_translation(story, language, english_data, voice_provider, flow, company_bot,
                                     response_json_story):
    """Create translation for a generic story from English to target language"""
    try:
        print(f"Creating translation for language: {language}")
        print(f"Story other_params: {story.other_params}")

        # Translate all English content to target language
        translated_data = {}

        TRANSLATABLE_FIELDS = ['title', 'content', 'tweet', 'objective', 'impact', 'micro_improvement', 'blurb']

        for field in TRANSLATABLE_FIELDS:
            if english_data.get(field):
                try:
                    translated_data[field] = translate_field(
                        voice_provider=voice_provider,
                        message_body=english_data[field],
                        target_language=language
                    )
                except Exception as e:
                    logger.info(f"Could not translate field {field}: {e}")
                    translated_data[field] = english_data[field]
            else:
                translated_data[field] = english_data.get(field, '')

        # Handle action_steps (can be string or list)
        action_steps = english_data.get('action_steps', [])
        if isinstance(action_steps, str) and action_steps.strip():
            try:
                translated_data['action_steps'] = translate_field(
                    voice_provider=voice_provider,
                    message_body=action_steps,
                    target_language=language
                )
            except Exception as e:
                logger.info(f"Could not translate action_steps: {e}")
                translated_data['action_steps'] = action_steps
        elif isinstance(action_steps, list):
            translated_action_steps = []
            for action_step in action_steps:
                if action_step:
                    try:
                        translated_step = translate_field(
                            voice_provider=voice_provider,
                            message_body=str(action_step),
                            target_language=language
                        )
                        translated_action_steps.append(translated_step)
                    except Exception as e:
                        logger.info(f"Could not translate action step: {e}")
                        translated_action_steps.append(str(action_step))
            translated_data['action_steps'] = translated_action_steps
        else:
            translated_data['action_steps'] = action_steps

        # Start with a complete copy of story's other_params
        translated_other_params = story.other_params.copy() if story.other_params else {}

        print(f"Initial translated_other_params: {translated_other_params}")

        # Translate duration if it contains text
        duration_value = translated_other_params.get('duration', '')
        if duration_value and ' ' in str(duration_value):
            try:
                translated_other_params['duration'] = translate_field(
                    voice_provider=voice_provider,
                    message_body=str(duration_value),
                    target_language=language
                )
            except Exception as e:
                logger.info(f"Could not translate duration: {e}")

        # Handle translation of complex nested structures (generic approach)
        def is_translatable_text(value, key=""):
            """
            Determine if a value should be translated based on content analysis,
            not field name dependencies
            """
            if not isinstance(value, str) or not value.strip():
                return False

            value = value.strip()
            technical_fields = ['flow', 'id', 'uuid', 'status', 'type', 'mode', 'version']
            if key.lower() in technical_fields:
                return False

            # Skip pure numbers
            if value.isdigit():
                return False

            # Skip if it looks like a code/ID (has numbers AND special chars, or is mixed case with numbers)
            has_digit = any(c.isdigit() for c in value)
            has_special = any(c in '-_' for c in value)
            if has_digit and (has_special or (value != value.lower() and value != value.upper())):
                # Things like "user-123", "test_id", "AbC123"
                if len(value) < 15:  # IDs are usually short
                    return False

            # Skip URLs, emails, file paths
            if (value.startswith(('http://', 'https://', 'ftp://', 'mailto:')) or
                    value.count('@') == 1 and '.' in value.split('@')[1] or
                    value.startswith(('.', '/', '\\')) or
                    value.lower().endswith(('.jpg', '.png', '.pdf', '.doc', '.xls', '.mp4', '.mp3'))):
                return False

            # Skip if it's mostly numbers or special characters
            alpha_count = sum(1 for c in value if c.isalpha())
            if alpha_count < len(value) * 0.5:  # Less than 50% alphabetic characters
                return False

            return True

        def translate_nested_structure(data, field_path=""):
            """Recursively translate nested data structures using intelligent content detection"""
            if isinstance(data, dict):
                translated_dict = {}
                for key, value in data.items():
                    current_path = f"{field_path}.{key}" if field_path else key

                    if isinstance(value, str) and is_translatable_text(value, key):
                        try:
                            translated_value = translate_field(
                                voice_provider=voice_provider,
                                message_body=value,
                                target_language=language
                            )
                            translated_dict[key] = translated_value
                            print(f"Auto-translated {current_path}: {value[:50]}... -> {translated_value[:50]}...")
                        except Exception as e:
                            logger.info(f"Could not translate {current_path}: {e}")
                            translated_dict[key] = value
                    elif isinstance(value, (dict, list)):
                        # Recursively handle nested structures
                        translated_dict[key] = translate_nested_structure(value, current_path)
                    else:
                        # Keep non-text values as-is
                        translated_dict[key] = value
                return translated_dict
            elif isinstance(data, list):
                return [translate_nested_structure(item, f"{field_path}[{i}]") for i, item in enumerate(data)]
            else:
                return data

        # Apply intelligent translation to ALL complex fields in other_params
        for field_name, field_value in list(translated_other_params.items()):
            if isinstance(field_value, (dict, list)):
                try:
                    original_value = field_value
                    translated_other_params[field_name] = translate_nested_structure(original_value, field_name)
                    print(f"Processed nested field: {field_name}")
                except Exception as e:
                    logger.info(f"Could not process nested field {field_name}: {e}")
            elif isinstance(field_value, str) and is_translatable_text(field_value, field_name):
                # Handle top-level string fields that need translation
                try:
                    translated_other_params[field_name] = translate_field(
                        voice_provider=voice_provider,
                        message_body=field_value,
                        target_language=language
                    )
                    print(f"Auto-translated top-level field {field_name}: {field_value[:50]}...")
                except Exception as e:
                    logger.info(f"Could not translate top-level field {field_name}: {e}")

        # Handle transliteration for specific fields (names, places) - these still need explicit handling
        if company_bot:
            try:
                voice_transliterate_provider = Voice.objects.filter(
                    company_bot=company_bot, type=VoiceType.Transliterate, language=language
                ).first()

                if story.location:
                    translated_other_params['location'] = story.location

                # Only transliterate fields that are specifically names/places (these need explicit handling)
                transliterate_fields = [
                    'user_name', 'location', 'organization', 'designation', 'district', 'block', 'village', 'panchayat',
                    'social_media'
                ]

                for field_name in transliterate_fields:
                    field_value = translated_other_params.get(field_name, '')
                    if field_value and str(field_value).strip():
                        try:
                            is_sentence = ' ' in str(field_value)
                            transliterated = transliterate_text(
                                voice_provider=voice_transliterate_provider,
                                message_body=str(field_value),
                                target_language=language,
                                source_language='en',
                                is_sentence=is_sentence
                            )
                            translated_other_params[field_name] = get_transliteration_output(data=transliterated)
                            print(
                                f"Transliterated {field_name}: {field_value} -> {translated_other_params[field_name]}")
                        except Exception as e:
                            logger.info(f"Could not transliterate field {field_name}: {e}")
                            # Keep original value if transliteration fails
                            translated_other_params[field_name] = str(field_value)
            except Exception as e:
                logger.info(f"Could not set up transliteration: {e}")

        print(f"Final translated_other_params: {translated_other_params}")

        # Create or update translation
        translation, created = StoryTranslation.objects.get_or_create(
            story=story,
            language=language,
            defaults={
                'title': translated_data.get('title', ''),
                'content': translated_data.get('content', ''),
                'tweet': translated_data.get('tweet', ''),
                'objective': translated_data.get('objective', ''),
                'action_steps': translated_data.get('action_steps', []),
                'impact': translated_data.get('impact', ''),
                'micro_improvement': translated_data.get('micro_improvement', ''),
                'blurb': translated_data.get('blurb', ''),
                'location': translated_other_params.get('location', ''),
                'other_params': translated_other_params,
                'formatted_content': ''
            }
        )

        if not created:
            # Update existing translation
            for field in TRANSLATABLE_FIELDS:
                if field in translated_data:
                    setattr(translation, field, translated_data[field])
            translation.action_steps = translated_data.get('action_steps', translation.action_steps)
            translation.location = translated_other_params.get('location', translation.location)
            translation.other_params = translated_other_params
            translation.save()

        print(f"Translation saved with other_params: {translation.other_params}")

        # Format translation content
        try:
            formatted_translation_content = get_formatted_story(translation)
            if formatted_translation_content:
                translation.formatted_content = formatted_translation_content
                translation.save(update_fields=['formatted_content'])
        except Exception as e:
            logger.info(f"Could not format translation content: {e}")

        logger.info(f"Created/Updated generic translation for story {story.id} in language {language}")
        return translation

    except Exception as e:
        logger.error(f'Error creating generic translation: %s', e, exc_info=True)
        return None


def get_generic_story_in_language(story, language='en'):
    """Get generic story content in specified language"""
    if language == 'en' or language == story.language:
        return {
            'title': story.title,
            'content': story.content,
            'tweet': story.tweet,
            'objective': story.objective,
            'action_steps': story.action_steps,
            'impact': story.impact,
            'micro_improvement': story.micro_improvement,
            'blurb': story.blurb,
            'location': story.location,
            'other_params': story.other_params,
        }

    try:
        translation = story.translations.get(language=language)
        return {
            'title': translation.title,
            'content': translation.content,
            'tweet': translation.tweet,
            'objective': translation.objective,
            'action_steps': translation.action_steps,
            'impact': translation.impact,
            'micro_improvement': translation.micro_improvement,
            'blurb': translation.blurb,
            'location': translation.location,
            'other_params': translation.other_params,
        }
    except StoryTranslation.DoesNotExist:
        return get_generic_story_in_language(story, 'en')
