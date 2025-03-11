from chatbot.models import StoryLanguageChoices, StoryStatusChoices, Story
from chatbot.models.geo_models import ProfileAddress
from chatbot.utils.story_llama_utils import translate_field, create_project
from chatbot.utils.story_utils.format_utils import clean_escaped_text


def save_story(response_json_story, language, voice_provider, profile, session, combined_reason):
    title = response_json_story.get('title', '')
    print('title: ', title)
    tweet = response_json_story.get('tweet', '')
    print('tweet: ', tweet)
    objective = response_json_story.get('objective', '')
    print('objective: ', objective)
    action_steps = response_json_story.get('action_steps', '')
    print('action_steps: ', action_steps)
    impact = response_json_story.get('impact', '')
    print('impact: ', impact)
    micro_improvement = response_json_story.get('micro_improvement', '')
    print('micro_improvement: ', micro_improvement)
    problem_statement = response_json_story.get('problem_statement', '')
    print('problem_statement: ', problem_statement)

    duration = response_json_story.get('duration', '')
    other_params = {
        'duration': duration
    }

    content = response_json_story.get('content', '')
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

    print("language used: ", language)
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
        action_steps = translate_field(
            voice_provider=voice_provider, message_body=action_steps, target_language=language
        )
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

    if profile:
        address = ProfileAddress.objects.filter(profile=profile).first()
        if address:
            location_parts = filter(None, [address.block, address.district, address.state])
            location = ", ".join(location_parts)
        else:
            location = ""
    else:
        location = ""

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
        profile=profile, problem_statement=problem_statement, language=language, voice_provider=voice_provider
    )

    return story, problem_statement
