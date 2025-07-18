import traceback
import logging
from chatbot.models import StoryLanguageChoices, StoryStatusChoices, Story, SessionFlowName, CompanyBot, Voice, \
    VoiceType
from chatbot.models.geo_models import ProfileAddress
from chatbot.utils.story_llama_utils import translate_field, create_project
from chatbot.utils.story_utils.challenges_utils import handle_challenges_solutions
from chatbot.utils.story_utils.format_utils import clean_escaped_text
from chatbot.utils.transliterate_utils import transliterate_text
from shikshalokam.models import Project, Task
from shikshalokam.serializer import TaskSerializer
import json_repair


logger = logging.getLogger('django')


def save_story(
        response_json_story, language, voice_provider, profile, session, combined_reason, flow=None, project_id=None,
        company_bot=None
):
    try:
        title = response_json_story['title']
        tweet = response_json_story.get('tweet', '')
        objective = response_json_story['objective']
        action_steps = response_json_story['action_steps']
        impact = response_json_story.get('impact', '')
        micro_improvement = response_json_story.get('micro_improvement', '')
        problem_statement = response_json_story['problem_statement']

        duration = response_json_story.get('duration', '')

        content = response_json_story['content']
        blurb = response_json_story.get('blurb', '')
        content = clean_escaped_text(text=content)
        title = clean_escaped_text(text=title)
        objective = clean_escaped_text(text=objective)
        blurb = clean_escaped_text(text=blurb)
        impact = clean_escaped_text(text=impact)
        problem_statement = clean_escaped_text(text=problem_statement)

        if flow and flow in [SessionFlowName.GuestMiStory]:
            user_name = response_json_story.get('user_name', '')
            location = response_json_story.get('location', '')
            organization = response_json_story.get('organization', '')
            designation = response_json_story.get('designation', '')
        else:
            user_name=profile.first_name if profile and profile.first_name else ''
            organization=None
            designation=None
            location = None
            if profile:
                address = ProfileAddress.objects.filter(profile=profile).first()
                if address:
                    location_parts = filter(None, [address.block, address.district, address.state])
                    location = ", ".join(location_parts)
                else:
                    location = ""

        if not title or not objective or not action_steps or not problem_statement:
            raise Exception("Empty fields found")

        logger.info(f"language used: %s", language)
        if language != 'en':
            title = translate_field(
                voice_provider=voice_provider, message_body=title, target_language=language
            )
            tweet = translate_field(
                voice_provider=voice_provider, message_body=tweet, target_language=language
            )
            objective = translate_field(
                voice_provider=voice_provider, message_body=objective, target_language=language
            )
            if isinstance(action_steps, str):
                action_steps = translate_field(
                    voice_provider=voice_provider, message_body=action_steps, target_language=language
                )
            else:
                action_steps = [
                    translate_field(
                        voice_provider=voice_provider,
                        message_body=action_step,
                        target_language=language
                    )
                    for action_step in action_steps
                ]

            impact = translate_field(
                voice_provider=voice_provider, message_body=impact, target_language=language
            )
            micro_improvement = translate_field(
                voice_provider=voice_provider, message_body=micro_improvement, target_language=language
            )
            problem_statement = translate_field(
                voice_provider=voice_provider, message_body=problem_statement, target_language=language
            )
            content = translate_field(
                voice_provider=voice_provider, message_body=content, target_language=language
            )
            blurb = translate_field(
                voice_provider=voice_provider, message_body=blurb, target_language=language
            )
            if flow and flow in [SessionFlowName.GuestMiStory] and company_bot:
                voice_transliterate_provider = Voice.objects.filter(
                    company_bot=company_bot, type=VoiceType.Transliterate, language=language
                ).first()

                if user_name and user_name != '':
                    is_sentence = ' ' in user_name
                    user_name = transliterate_text(
                        voice_provider=voice_transliterate_provider, message_body=user_name, target_language=language,
                        source_language='en',
                        is_sentence=is_sentence
                    )
                    user_name = get_transliteration_output(data=user_name)
                if organization and organization != '':
                    is_sentence = ' ' in organization
                    organization = transliterate_text(
                        voice_provider=voice_transliterate_provider, message_body=organization,
                        target_language=language,
                        source_language='en',
                        is_sentence=is_sentence
                    )
                    organization = get_transliteration_output(data=organization)
                if designation and designation != '':
                    is_sentence = ' ' in designation
                    designation = transliterate_text(
                        voice_provider=voice_transliterate_provider, message_body=designation,
                        target_language=language,
                        source_language='en',
                        is_sentence=is_sentence
                    )
                    designation = get_transliteration_output(data=designation)


        if flow == SessionFlowName.Reflection and project_id:
            logger.info(f"project_id: %s", project_id)
            project = Project.objects.get(project_id=project_id)
            if project:
                tasks = Task.objects.filter(project=project)
                serialized_tasks = TaskSerializer(tasks, many=True).data
                # action_steps = [task.get('task_name') for task in serialized_tasks]
                action_steps = [f"{idx + 1}. {task.get('task_name')}" for idx, task in enumerate(serialized_tasks)]

        other_params = {
            'duration': duration,
            'flow': flow,
            'user_name': user_name,
        }

        if flow and flow in [SessionFlowName.GuestMiStory]:
            other_params['user_name'] = user_name
            other_params['location'] = location
            other_params['organization'] = organization
            other_params['designation'] = designation

        story = Story.objects.filter(session=session).first()
        if story:
            story.title = title
            story.content = content
            story.tweet = tweet
            story.author = profile
            story.objective = objective
            story.action_steps = action_steps
            story.impact = impact
            story.micro_improvement = micro_improvement
            story.language = language
            story.stage = StoryStatusChoices.COMPLETED
            story.other_params = other_params
            story.location = location if location else ""
            story.blurb = blurb
            story.validation_logs = combined_reason
        else:
            story = Story(
                title=title,
                content=content,
                tweet=tweet,
                author=profile,
                session=session,
                objective=objective,
                action_steps=action_steps,
                impact=impact,
                micro_improvement=micro_improvement,
                language=language,
                stage=StoryStatusChoices.COMPLETED,
                other_params=other_params,
                location=location if location else "",
                blurb=blurb,
                validation_logs=combined_reason
            )
        story.save()

        create_project(
            response_json=response_json_story, title=title, objective=objective, story=story,
            profile=profile, problem_statement=problem_statement, language=language, voice_provider=voice_provider,
            project_id=project_id
        )

        return story, problem_statement
    except Exception as e:
        logger.error('Error Occured: %s', e, exc_info=True)
        traceback.print_exc()
        raise Exception("Failed to save mi story")


def save_chaupal_report(
        response_json_story, language, company_bot, voice_provider, profile, session, combined_reason, flow=None, messages=[]
):
    try:
        title = response_json_story['title']
        challenges_faced = response_json_story['challenges_faced']
        solutions_discussed = response_json_story['solutions_discussed']

        user_name = response_json_story.get('user_name', '')
        user_location = response_json_story.get('location', '')
        organization = response_json_story.get('organization', '')
        participants_count = response_json_story.get('participants_count', '')
        discussion_date = response_json_story.get('discussion_date', '')

        title = clean_escaped_text(text=title)
        if solutions_discussed and len(solutions_discussed) > 0 and challenges_faced and len(challenges_faced) > 0:
            challenges_faced, solutions_discussed = handle_challenges_solutions(
                challenges_faced=challenges_faced, solutions_discussed=solutions_discussed, profile=profile,
                messages=messages
            )

        logger.info(f"language used: %s", language)
        if language != 'en':
            voice_transliterate_provider = Voice.objects.filter(
                company_bot=company_bot, type=VoiceType.Transliterate, language=language
            ).first()
            if user_name and user_name != '':
                user_name = transliterate_text(
                    voice_provider=voice_transliterate_provider, message_body=user_name, target_language=language,
                    source_language='en'
                )
                user_name=get_transliteration_output(data=user_name)
            if organization and organization != '':
                organization = transliterate_text(
                    voice_provider=voice_transliterate_provider, message_body=organization, target_language=language,
                    source_language='en'
                )
                organization = get_transliteration_output(data=organization)
            title = translate_field(
                voice_provider=voice_provider, message_body=title, target_language=language
            )
            if isinstance(challenges_faced, str):
                challenges_faced = json_repair.repair_json(challenges_faced, return_objects=True)

            challenges_faced = [
                translate_field(
                    voice_provider=voice_provider,
                    message_body=challenge,
                    target_language=language
                )
                for challenge in challenges_faced
            ]

            if isinstance(solutions_discussed, str):
                solutions_discussed = json_repair.repair_json(solutions_discussed, return_objects=True)

            solutions_discussed = [
                translate_field(
                    voice_provider=voice_provider,
                    message_body=solution,
                    target_language=language
                )
                for solution in solutions_discussed
            ]

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
            'challenges_faced': challenges_faced,
            'solutions_discussed': solutions_discussed,
            'user_name': user_name,
            'location': user_location,
            'organization': organization,
            'participants_count': participants_count,
            'discussion_date': discussion_date,
            'flow': flow
        }

        story = Story.objects.filter(session=session).first()
        if story:
            story.title = title
            story.other_params = other_params
            story.stage = StoryStatusChoices.COMPLETED
            story.location = location
            story.validation_logs = combined_reason
        else:
            story = Story(
                title=title,
                author=profile,
                session=session,
                stage=StoryStatusChoices.COMPLETED,
                location=location,
                validation_logs=combined_reason,
                language=language,
                other_params=other_params
            )
        story.save()

        return story, None
    except Exception as e:
        logger.error('Error Occured: %s', e, exc_info=True)
        traceback.print_exc()
        raise Exception("Failed to save chaupal report")


def get_transliteration_output(data):
    if data and isinstance(data, dict):
        data = data.get('content', [])
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]

    return None


def save_ptm_story(
        response_json_story, language, voice_provider, profile, session, combined_reason, flow=None,
        company_bot=None
):
    try:
        name = response_json_story.get("name", "")
        district = response_json_story.get("district", "")
        school = response_json_story.get("school", "")
        role = response_json_story.get("role", "")
        ptm_experience_summary = response_json_story.get("ptm_experience_summary", "")
        key_highlights = response_json_story.get("key_highlights", "")
        perceived_changes_or_impact = response_json_story.get("perceived_changes_or_impact", "")

        # if language != "en":
        #     ptm_experience_summary = translate_field(voice_provider, ptm_experience_summary, target_language=language)
        #     key_highlights = translate_field(voice_provider, key_highlights, target_language=language)
        #     expected_impact = translate_field(voice_provider, expected_impact, target_language=language)
        #
        #     voice_transliterate_provider = Voice.objects.filter(
        #         company_bot=company_bot, type=VoiceType.Transliterate, language=language
        #     ).first()
        #
        #     if name and name != '':
        #         is_sentence = ' ' in name
        #         name = transliterate_text(
        #             voice_provider=voice_transliterate_provider, message_body=name, target_language=language,
        #             source_language='en',
        #             is_sentence=is_sentence
        #         )
        #         name = get_transliteration_output(data=name)
        #
        #     name = translate_field(voice_provider, name, target_language=language)
        #     district = translate_field(voice_provider, district, target_language=language)
        #     school = translate_field(voice_provider, school, target_language=language)
        #     role = translate_field(voice_provider, role, target_language=language)

        other_params = {
            "user_name": name,
            "district": district,
            "school": school,
            "role": role,
            "ptm_experience_summary": ptm_experience_summary,
            "key_highlights": key_highlights,
            "perceived_changes_or_impact": perceived_changes_or_impact,
            "flow": flow,
        }

        title = f"{name}'s PTM Reflection" if name and name != '' else "PTM Reflection"

        story = Story.objects.filter(session=session).first()
        if story:
            story.title = title
            story.language = language
            story.stage = StoryStatusChoices.COMPLETED
            story.other_params = other_params
            story.validation_logs = combined_reason
        else:
            story = Story(
                title=title,
                author=profile,
                session=session,
                language=language,
                stage=StoryStatusChoices.COMPLETED,
                other_params=other_params,
                validation_logs=combined_reason
            )
        story.save()
        return story, ptm_experience_summary
    except Exception as e:
        logger.error("Error in save_ptm_story: %s", e, exc_info=True)
        traceback.print_exc()
        raise Exception("Failed to save PTM story")
