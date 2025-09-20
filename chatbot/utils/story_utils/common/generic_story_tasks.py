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

    # Define Story model fields that map directly
    STORY_MODEL_FIELDS = {
        'title', 'content', 'tweet', 'objective', 'action_steps',
        'impact', 'micro_improvement', 'blurb', 'language', 'stage',
        'other_params', 'location', 'validation_logs'
    }

    # Add ALL other fields from JSON to other_params (not just specific ones)
    for key, value in response_json_story.items():
        if key not in STORY_MODEL_FIELDS:
            other_params[key] = value

    print(f"Story other_params before save: {other_params}")

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
    # Return problem_statement from JSON if it exists
    problem_statement = clean_escaped_text(text=response_json_story.get('problem_statement', ''))
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
                    logger.warning(f"Could not translate field {field}: {e}")
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
                logger.warning(f"Could not translate action_steps: {e}")
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
                        logger.warning(f"Could not translate action step: {e}")
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
                logger.warning(f"Could not translate duration: {e}")

        # Handle transliteration for specific fields
        if company_bot:
            try:
                voice_transliterate_provider = Voice.objects.filter(
                    company_bot=company_bot, type=VoiceType.Transliterate, language=language
                ).first()

                # Include all fields that might need transliteration
                transliterate_fields = ['user_name', 'location', 'organization', 'designation', 'district', 'block']

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
                            logger.warning(f"Could not transliterate field {field_name}: {e}")
                            # Keep original value if transliteration fails
                            translated_other_params[field_name] = str(field_value)
            except Exception as e:
                logger.warning(f"Could not set up transliteration: {e}")

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
