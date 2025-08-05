import traceback
import logging
from chatbot.models import StoryStatusChoices, Story, Voice, VoiceType, StoryTranslation
from chatbot.models.geo_models import ProfileAddress
from chatbot.utils.story_llama_utils import translate_field
from chatbot.utils.story_utils.challenges_utils import handle_challenges_solutions
from chatbot.utils.story_utils.format_utils import clean_escaped_text
from chatbot.utils.transliterate_utils import transliterate_text, get_transliteration_output
import json_repair


logger = logging.getLogger('django')


def save_chaupal_report(
        response_json_story, language, company_bot, voice_provider, profile, session, combined_reason, flow=None,
        messages=[]
):
    try:
        english_title = clean_escaped_text(text=response_json_story['title'])
        english_challenges_faced = response_json_story['challenges_faced']
        english_solutions_discussed = response_json_story['solutions_discussed']

        user_name = response_json_story.get('user_name', '')
        user_location = response_json_story.get('location', '')
        organization = response_json_story.get('organization', '')
        participants_count = response_json_story.get('participants_count', '')
        discussion_date = response_json_story.get('discussion_date', '')

        if english_solutions_discussed and len(english_solutions_discussed) > 0 and english_challenges_faced and len(
                english_challenges_faced) > 0:
            english_challenges_faced, english_solutions_discussed = handle_challenges_solutions(
                challenges_faced=english_challenges_faced, solutions_discussed=english_solutions_discussed,
                profile=profile, messages=messages
            )

        if profile:
            address = ProfileAddress.objects.filter(profile=profile).first()
            if address:
                location_parts = filter(None, [address.block, address.district, address.state])
                location = ", ".join(location_parts)
            else:
                location = ""
        else:
            location = ""

        other_params = {
            'challenges_faced': english_challenges_faced,
            'solutions_discussed': english_solutions_discussed,
            'user_name': user_name,
            'location': user_location,
            'organization': organization,
            'participants_count': participants_count,
            'discussion_date': discussion_date,
            'flow': flow
        }

        story = Story.objects.filter(session=session).first()
        if story:
            story.title = english_title
            story.other_params = other_params
            story.stage = StoryStatusChoices.COMPLETED
            story.location = location
            story.validation_logs = combined_reason
            story.language = 'en'
        else:
            story = Story(
                title=english_title,
                author=profile,
                session=session,
                stage=StoryStatusChoices.COMPLETED,
                location=location,
                validation_logs=combined_reason,
                language='en',
                other_params=other_params
            )
        story.save()

        if language != 'en':
            create_chaupal_translation(
                story=story,
                language=language,
                english_title=english_title,
                english_challenges_faced=english_challenges_faced,
                english_solutions_discussed=english_solutions_discussed,
                voice_provider=voice_provider,
                company_bot=company_bot,
                other_data={
                    'user_name': user_name,
                    'organization': organization
                }
            )

        return story, None
    except Exception as e:
        logger.error('Error Occurred: %s', e, exc_info=True)
        traceback.print_exc()
        raise Exception("Failed to save chaupal report")


def create_chaupal_translation(story, language, english_title, english_challenges_faced, english_solutions_discussed,
                               voice_provider, company_bot, other_data):
    """Create translation for chaupal report"""
    try:
        translated_title = translate_field(
            voice_provider=voice_provider, message_body=english_title, target_language=language
        )

        if isinstance(english_challenges_faced, str):
            english_challenges_faced = json_repair.repair_json(english_challenges_faced, return_objects=True)

        translated_challenges_faced = [
            translate_field(
                voice_provider=voice_provider,
                message_body=challenge,
                target_language=language
            )
            for challenge in english_challenges_faced
        ]

        if isinstance(english_solutions_discussed, str):
            english_solutions_discussed = json_repair.repair_json(english_solutions_discussed, return_objects=True)

        translated_solutions_discussed = [
            translate_field(
                voice_provider=voice_provider,
                message_body=solution,
                target_language=language
            )
            for solution in english_solutions_discussed
        ]

        translated_other_params = {
            'challenges_faced': translated_challenges_faced,
            'solutions_discussed': translated_solutions_discussed
        }

        voice_transliterate_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.Transliterate, language=language
        ).first()

        for field_name in ['user_name', 'organization']:
            field_value = other_data.get(field_name, '')
            if field_value and field_value != '':
                transliterated = transliterate_text(
                    voice_provider=voice_transliterate_provider,
                    message_body=field_value,
                    target_language=language,
                    source_language='en'
                )
                translated_other_params[field_name] = get_transliteration_output(data=transliterated)

        translation, created = StoryTranslation.objects.get_or_create(
            story=story,
            language=language,
            defaults={
                'title': translated_title,
                'content': '',
                'translated_other_params': translated_other_params
            }
        )

        if not created:
            translation.title = translated_title
            translation.translated_other_params = translated_other_params
            translation.save()

        return translation

    except Exception as e:
        logger.error(f'Error creating chaupal translation: %s', e, exc_info=True)
        return None
