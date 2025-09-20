import logging
import json
from chatbot.models import StoryStatusChoices, Story, Voice, VoiceType, StoryTranslation
from chatbot.models.geo_models import ProfileAddress
from chatbot.models.story_vernacular_model import StoryVernacular
from chatbot.utils.story_llama_utils import translate_field
from chatbot.utils.story_utils.format_utils import clean_escaped_text, get_formatted_story
from chatbot.utils.transliterate_utils import transliterate_text, get_transliteration_output

logger = logging.getLogger('django')


def save_generic_story(
        response_json_story, language, voice_provider, profile, session, combined_reason, flow=None, project_id=None,
        company_bot=None
):
    """
    Generic save story function that saves the response JSON as-is while ensuring it's valid JSON.
    Maps JSON fields to Story model fields if they exist.
    """
    # Validate that response_json_story is valid JSON
    if isinstance(response_json_story, str):
        try:
            response_json_story = json.loads(response_json_story)
        except json.JSONDecodeError:
            raise Exception("Invalid JSON response from story generation")

    # Ensure response_json_story is a dictionary
    if not isinstance(response_json_story, dict):
        raise Exception("Response must be a valid JSON object")

    # Parse JSON strings within the response
    def parse_json_strings(data):
        """Parse JSON strings that are arrays [] or objects {} within the data"""
        if isinstance(data, dict):
            parsed_data = {}
            for key, value in data.items():
                if isinstance(value, str) and value.strip():
                    # Check if string starts and ends with [] or {}
                    stripped_value = value.strip()
                    if ((stripped_value.startswith('[') and stripped_value.endswith(']')) or
                            (stripped_value.startswith('{') and stripped_value.endswith('}'))):
                        try:
                            parsed_data[key] = json.loads(stripped_value)
                        except json.JSONDecodeError:
                            # If parsing fails, keep the original string
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

    # Get title from StoryVernacular if not present in response_json_story
    if 'title' not in response_json_story and company_bot:
        try:
            story_vernacular = StoryVernacular.objects.filter(
                company_bot=company_bot, language=language
            ).first()

            if story_vernacular and story_vernacular.translation_json:
                vernacular_title = story_vernacular.translation_json.get('title')
                if vernacular_title:
                    response_json_story['title'] = vernacular_title
                    logger.info(f"Used StoryVernacular title for language {language}")
        except Exception as e:
            logger.warning(f"Could not get title from StoryVernacular: {e}")

    # Define Story model fields that need text cleaning
    CLEANABLE_FIELDS = {'title', 'content', 'blurb', 'objective', 'impact'}

    # Define Story model fields (excluding relationships, auto fields, etc.)
    STORY_MODEL_FIELDS = {
        'title', 'content', 'tweet', 'objective', 'action_steps',
        'impact', 'micro_improvement', 'blurb', 'language', 'stage',
        'other_params', 'location', 'validation_logs'
    }

    # Define fields that need transliteration
    TRANSLITERATION_FIELDS = {'location', 'district', 'block', 'user_name'}

    # Get basic profile information
    user_name = profile.first_name if profile and profile.first_name else ''
    fallback_location = ""
    if profile:
        address = ProfileAddress.objects.filter(profile=profile).first()
        if address:
            location_parts = filter(None, [address.block, address.district, address.state])
            fallback_location = ", ".join(location_parts)

    # Process fields from JSON response
    story_fields = {}
    other_params = {
        'flow': flow,
    }

    # Handle transliteration fields first
    transliterated_data = {}
    if company_bot:
        try:
            voice_transliterate_provider = Voice.objects.filter(
                company_bot=company_bot, type=VoiceType.Transliterate, language='en'
            ).first()

            for field_name in TRANSLITERATION_FIELDS:
                if field_name in response_json_story:
                    field_value = response_json_story[field_name]
                    if field_value and str(field_value).strip():
                        try:
                            is_sentence = ' ' in str(field_value)
                            transliterated = transliterate_text(
                                voice_provider=voice_transliterate_provider,
                                message_body=str(field_value),
                                target_language='en',
                                source_language='en',
                                is_sentence=is_sentence
                            )
                            transliterated_data[field_name] = get_transliteration_output(data=transliterated)
                        except Exception as e:
                            logger.warning(f"Could not transliterate field {field_name}: {e}")
                            transliterated_data[field_name] = str(field_value)
        except Exception as e:
            logger.warning(f"Could not set up transliteration: {e}")

    # Process all fields from JSON response
    for key, value in response_json_story.items():
        processed_value = value

        # Clean text fields that need cleaning
        if key in CLEANABLE_FIELDS and isinstance(value, str):
            processed_value = clean_escaped_text(text=value)

        # Use transliterated value if available
        if key in transliterated_data:
            processed_value = transliterated_data[key]

        # Assign to appropriate dict
        if key in STORY_MODEL_FIELDS:
            story_fields[key] = processed_value
        else:
            other_params[key] = processed_value

    # Add fallback values for required fields
    if 'user_name' not in other_params and user_name:
        other_params['user_name'] = user_name

    if 'location' not in story_fields and fallback_location:
        story_fields['location'] = fallback_location
    elif 'location' not in story_fields:
        story_fields['location'] = ""

    # Set required Story model defaults
    story_fields.update({
        'author': profile,
        'session': session,
        'language': 'en',
        'stage': StoryStatusChoices.COMPLETED,
        'other_params': other_params,
        'validation_logs': combined_reason
    })

    # Check if story already exists for this session
    story = Story.objects.filter(session=session).first()
    if story:
        # Update existing story
        for field, value in story_fields.items():
            if hasattr(story, field):
                setattr(story, field, value)
    else:
        # Create new story
        story = Story(**story_fields)

    story.save()

    # Create translation if language is not English
    if language != 'en':
        create_generic_story_translation(
            story=story,
            language=language,
            voice_provider=voice_provider,
            flow=flow,
            company_bot=company_bot,
            response_json=response_json_story,
            profile_data=transliterated_data or {'user_name': user_name, 'location': story_fields.get('location', '')}
        )

    logger.info(f"Successfully saved generic story for flow {flow}, session {session}")
    # Return problem_statement from JSON if it exists
    problem_statement = clean_escaped_text(text=response_json_story.get('problem_statement', ''))
    return story, problem_statement


def create_generic_story_translation(story, language, voice_provider, flow, company_bot, response_json, profile_data):
    """Create translation for a generic story - Updated signature"""
    try:
        # Define fields that need translation
        TRANSLATABLE_FIELDS = {
            'title', 'content', 'tweet', 'objective', 'impact',
            'micro_improvement', 'blurb'
        }

        translated_data = {}

        # Get English data from story
        english_data = {
            'title': story.title,
            'content': story.content,
            'tweet': story.tweet,
            'objective': story.objective,
            'impact': story.impact,
            'micro_improvement': story.micro_improvement,
            'blurb': story.blurb,
            'action_steps': story.action_steps
        }

        # Translate standard fields
        for field in TRANSLATABLE_FIELDS:
            if english_data.get(field):
                try:
                    translated_data[field] = translate_field(
                        voice_provider=voice_provider,
                        message_body=english_data[field],
                        target_language=language
                    )
                except Exception as e:
                    logger.warning(f"Could not translate field {field}: {e}")
                    translated_data[field] = english_data[field]

        # Handle action_steps (can be string or list)
        action_steps = english_data['action_steps']
        if isinstance(action_steps, str) and action_steps.strip():
            translated_data['action_steps'] = translate_field(
                voice_provider=voice_provider, message_body=action_steps, target_language=language
            )
        elif isinstance(action_steps, list):
            translated_data['action_steps'] = [
                translate_field(
                    voice_provider=voice_provider,
                    message_body=str(action_step),
                    target_language=language
                )
                for action_step in action_steps if action_step
            ]
        else:
            translated_data['action_steps'] = action_steps

        # Prepare other_params for translation
        translated_other_params = profile_data.copy() if profile_data else {}

        # Copy non-translatable params from original other_params
        original_other_params = story.other_params or {}
        for key, value in original_other_params.items():
            if key not in ['user_name', 'location'] and key not in translated_other_params:
                translated_other_params[key] = value

        # Translate duration if it contains text
        if translated_other_params.get('duration') and ' ' in str(translated_other_params['duration']):
            try:
                translated_other_params['duration'] = translate_field(
                    voice_provider=voice_provider,
                    message_body=str(translated_other_params['duration']),
                    target_language=language
                )
            except Exception as e:
                logger.warning(f"Could not translate duration: {e}")

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
                'other_params': translated_other_params,
                'formatted_content': ''
            }
        )

        if not created:
            for field in TRANSLATABLE_FIELDS:
                if field in translated_data:
                    setattr(translation, field, translated_data[field])
            translation.action_steps = translated_data.get('action_steps', translation.action_steps)
            translation.other_params = translated_other_params
            translation.save()

        # Format translation content
        try:
            formatted_translation_content = get_formatted_story(translation)
            if formatted_translation_content:
                translation.formatted_content = formatted_translation_content
                translation.save(update_fields=['formatted_content'])
        except Exception as e:
            logger.warning(f"Could not format translation content: {e}")

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
            'other_params': translation.other_params,
        }
    except StoryTranslation.DoesNotExist:
        return get_generic_story_in_language(story, 'en')
