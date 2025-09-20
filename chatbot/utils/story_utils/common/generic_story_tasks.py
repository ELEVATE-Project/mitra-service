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
    Generic save story function that saves English content to Story model
    and creates translations for other languages.
    Assumes response_json_story contains English content.
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

    # Extract English content (assuming source is English)
    english_title = clean_escaped_text(text=response_json_story.get('title', ''))
    english_content = clean_escaped_text(text=response_json_story.get('content', ''))
    english_tweet = response_json_story.get('tweet', '')
    english_objective = clean_escaped_text(text=response_json_story.get('objective', ''))
    english_impact = clean_escaped_text(text=response_json_story.get('impact', ''))
    english_micro_improvement = response_json_story.get('micro_improvement', '')
    english_blurb = clean_escaped_text(text=response_json_story.get('blurb', ''))
    english_action_steps = response_json_story.get('action_steps', [])

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
            logger.warning(f"Could not get title from StoryVernacular: {e}")

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

    # Add other non-translatable fields from JSON
    NON_TRANSLATABLE_FIELDS = {
        'duration', 'organization', 'designation', 'location', 'district', 'block'
    }

    for key, value in response_json_story.items():
        if key in NON_TRANSLATABLE_FIELDS:
            other_params[key] = value

    # Use fallback location if not provided
    location = response_json_story.get('location', fallback_location)

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
            other_data={
                'user_name': user_name,
                'location': location,
                'organization': response_json_story.get('organization', ''),
                'designation': response_json_story.get('designation', ''),
                'duration': response_json_story.get('duration', '')
            }
        )

    logger.info(f"Successfully saved generic story for flow {flow}, session {session}")
    # Return problem_statement from JSON if it exists
    problem_statement = clean_escaped_text(text=response_json_story.get('problem_statement', ''))
    return story, problem_statement


def create_generic_story_translation(story, language, english_data, voice_provider, flow, company_bot, other_data):
    """Create translation for a generic story from English to target language"""
    try:
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
                    logger.warning(f"Could not translate field {field}: {e}")
                    translated_data[field] = english_data[field]

        # Handle action_steps (can be string or list)
        action_steps = english_data['action_steps']
        if isinstance(action_steps, str) and action_steps.strip():
            translated_data['action_steps'] = translate_field(
                voice_provider=voice_provider,
                message_body=action_steps,
                target_language=language
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
        translated_other_params = story.other_params.copy() if story.other_params else {}

        # Translate duration if it contains text
        if other_data.get('duration') and ' ' in str(other_data['duration']):
            try:
                translated_other_params['duration'] = translate_field(
                    voice_provider=voice_provider,
                    message_body=str(other_data['duration']),
                    target_language=language
                )
            except Exception as e:
                logger.warning(f"Could not translate duration: {e}")
        elif other_data.get('duration'):
            translated_other_params['duration'] = other_data['duration']

        # Handle transliteration for specific fields
        if company_bot:
            try:
                voice_transliterate_provider = Voice.objects.filter(
                    company_bot=company_bot, type=VoiceType.Transliterate, language=language
                ).first()

                transliterate_fields = ['user_name', 'location', 'organization', 'designation']

                for field_name in transliterate_fields:
                    field_value = other_data.get(field_name, '')
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
                        except Exception as e:
                            logger.warning(f"Could not transliterate field {field_name}: {e}")
                            translated_other_params[field_name] = str(field_value)
            except Exception as e:
                logger.warning(f"Could not set up transliteration: {e}")

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
