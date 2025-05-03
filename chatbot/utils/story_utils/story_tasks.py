import traceback

from chatbot.models import StoryLanguageChoices, StoryStatusChoices, Story, SessionFlowName, CompanyBot
from chatbot.models.geo_models import ProfileAddress
from chatbot.utils.story_llama_utils import translate_field, create_project
from chatbot.utils.story_utils.challenges_utils import handle_challenges_solutions
from chatbot.utils.story_utils.format_utils import clean_escaped_text
from chatbot.utils.transliterate_utils import transliterate_text
from shikshalokam.models import Project, Task
from shikshalokam.serializer import TaskSerializer
import json_repair


def save_story(
        response_json_story, language, voice_provider, profile, session, combined_reason, flow=None, project_id=None
):
    try:
        title = response_json_story['title']
        print('title: ', title)
        tweet = response_json_story.get('tweet', '')
        print('tweet: ', tweet)
        objective = response_json_story['objective']
        print('objective: ', objective)
        action_steps = response_json_story['action_steps']
        print('action_steps: ', action_steps)
        impact = response_json_story.get('impact', '')
        print('impact: ', impact)
        micro_improvement = response_json_story.get('micro_improvement', '')
        print('micro_improvement: ', micro_improvement)
        problem_statement = response_json_story['problem_statement']
        print('problem_statement: ', problem_statement)

        duration = response_json_story.get('duration', '')

        content = response_json_story['content']
        print('content: ', content)
        blurb = response_json_story.get('blurb', '')
        print('blurb: ', blurb)
        content = clean_escaped_text(text=content)
        print('clean content: ', content)
        title = clean_escaped_text(text=title)
        objective = clean_escaped_text(text=objective)
        blurb = clean_escaped_text(text=blurb)
        impact = clean_escaped_text(text=impact)
        problem_statement = clean_escaped_text(text=problem_statement)
        user_name=''
        if not title or not objective or not action_steps or not problem_statement:
            raise Exception("Empty fields found")

        print("language used: ", language)
        if language != 'en':
            transliterate_bot = CompanyBot.objects.filter(route='/transliterate').first()
            user_name = transliterate_text(transliterate_bot, 'en', language, profile.first_name)

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

        if flow == SessionFlowName.Reflection and project_id:
            print("project_id: ", project_id)
            project = Project.objects.get(project_id=project_id)
            if project:
                print("project: ", project)
                tasks = Task.objects.filter(project=project)
                serialized_tasks = TaskSerializer(tasks, many=True).data
                print("tasks serialized_tasks: ", serialized_tasks)
                # action_steps = [task.get('task_name') for task in serialized_tasks]
                action_steps = [f"{idx + 1}. {task.get('task_name')}" for idx, task in enumerate(serialized_tasks)]
                print("tasks action_steps: ", action_steps)

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
            'duration': duration,
            'flow': flow,
            'user_name': user_name,
        }

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
            story.language = StoryLanguageChoices.ENGLISH
            story.stage = StoryStatusChoices.COMPLETED
            story.other_params = other_params
            story.location = location
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
                language=StoryLanguageChoices.ENGLISH,
                stage=StoryStatusChoices.COMPLETED,
                other_params=other_params,
                location=location,
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
        print("Error Occured: ", e)
        traceback.print_exc()
        raise Exception("Failed to save mi story")


def save_chaupal_report(response_json_story, language, voice_provider, profile, session, combined_reason, flow=None, messages=[]):
    try:
        title = response_json_story['title']
        print('title: ', title)
        challenges_faced = response_json_story['challenges_faced']
        print('challenges_faced: ', challenges_faced)
        solutions_discussed = response_json_story['solutions_discussed']
        print('solutions_discussed: ', solutions_discussed)

        user_name = response_json_story.get('user_name', '')
        user_location = response_json_story.get('location', '')
        organization = response_json_story.get('organization', '')
        participants_count = response_json_story.get('participants_count', '')
        discussion_date = response_json_story.get('discussion_date', '')

        title = clean_escaped_text(text=title)

        challenges_faced, solutions_discussed = handle_challenges_solutions(
            challenges_faced=challenges_faced, solutions_discussed=solutions_discussed, profile=profile,
            messages=messages
        )

        print("language used: ", language)
        if language != 'en':
            transliterate_bot = CompanyBot.objects.filter(route='/transliterate').first()
            user_name = transliterate_text(transliterate_bot, 'en', language, user_name)
            organization = transliterate_text(voice_provider.company_bot, 'en', language, organization)

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
        print("Error Occured: ", e)
        traceback.print_exc()
        raise Exception("Failed to save chaupal report")
