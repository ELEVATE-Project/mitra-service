import re
import json_repair
from chatbot.pdf.shiksha_chaupal.story_images_page import get_report_images_page_html
from chatbot.utils.story_llama_utils import translate_field


def get_mom_report_html(story, story_vernacular, voice_provider, profile):
    print("story.action_steps: ", story.other_params)
    if story.other_params:
        challenges_faced = story.other_params.get('challenges_faced')
        solutions_discussed = story.other_params.get('solutions_discussed')
    else:
        challenges_faced, solutions_discussed = None, None
    translation_json = story_vernacular.translation_json
    if translation_json:
        translation_json = translation_json.get('second_page', {})
    else:
        translation_json = {}

    challenges_html = process_steps(
        raw_data=challenges_faced, fallback_text=translation_json.get('no_challenges_faced_text', "")
    )
    solutions_html = process_steps(
        raw_data=solutions_discussed, fallback_text=translation_json.get('no_solutions_text', "")
    )

    author, address_string, company_logo = get_user_details(
        story=story, profile=profile, voice_provider=voice_provider
    )

    page_html = f"""
    <div class="story-second-page-container">
        <div style="width: 100%; margin-top: 10px;">
            <div style="display: flex; justify-content: end;">
                <img src="{company_logo}" 
                    style="width: 200px; height: auto; object-fit: contain;"
                    alt="Bottom Logo">
            </div>
        </div>
        <h1>{story.title}</h1>
        <p>{author}</p>
        <p>{address_string}</p>
        <div class="story-second-page-section story-action-steps">
            <h2>{translation_json.get('heading2', "Challenges")}</h2>
            {challenges_html or translation_json.get('no_challenges_faced_text', "")}
        </div>
        <div class="story-second-page-section story-action-steps">
            <h2>{translation_json.get('heading3', "Solutions")}</h2>
            {solutions_html or translation_json.get('no_solutions_text', "")}
        </div>
        {get_report_images_page_html(story=story)}
    </div>
    """
    return page_html

def clean_escaped_text(text):
    text = text.replace("\\'", "")# \'  →  '
    text = text.replace('\\"', '')# \"  →  "
    text = text.replace("\\\\", "") # \\  →  \
    print("Text: ", text)
    return text


def process_steps(raw_data, fallback_text):
    if isinstance(raw_data, str):
        try:
            if raw_data.strip().startswith("["):
                raw_data = json_repair.repair_json(raw_data, return_objects=True)
                print("Processed JSON:", raw_data)
            else:
                raw_data = [raw_data]
        except Exception as e:
            print(f"Error repairing JSON: {e}")
            raw_data = [fallback_text]

    steps = (
        [clean_escaped_text(step) for step in raw_data] if isinstance(raw_data, list)
        else [clean_escaped_text(raw_data)] if isinstance(raw_data, str)
        else [fallback_text]
    )

    print("Processed steps: ", steps)

    if (steps and isinstance(steps, list) and len(steps) == 1 and isinstance(steps[0], str)):
        steps_text = steps[0]
        split_steps = re.findall(r'\d+\.\s*[^0-9]+', steps_text)
        split_steps = [step.strip() for step in split_steps if step.strip()]
        if not split_steps:
            split_steps = steps
    elif steps and isinstance(steps, str):
        steps_text = " ".join(steps)
        split_steps = re.findall(r'\d+\.\s*[^.]+', steps_text)
        split_steps = [step.strip() for step in split_steps if step.strip()]
    else:
        split_steps = [step.strip() for step in steps if step.strip()]

    print("\n\nsplit_steps: ", split_steps)

    steps_html = (
        f"<ol style='list-style-type: none; padding: 0; margin: 0;'>"
        + ''.join(f"<li>{step}</li>" for step in split_steps)
        + "</ol>"
    )

    print("\n\nsteps_html: ", steps_html)
    return steps_html or fallback_text


def get_user_details(story, profile, voice_provider):
    profile_addresses=None
    if profile:
        profile_addresses = profile.profile_address.all().first()
        company_logo = profile.company.get_public_url()
    else:
        company_logo = voice_provider.company_bot.company.get_public_url()
    print("logo: ", company_logo)

    address_components = [
        profile_addresses.district if profile_addresses and profile_addresses.district else "",
        profile_addresses.block if profile_addresses and profile_addresses.block else "",
        profile_addresses.state if profile_addresses and profile_addresses.state else ""
    ]

    address_string = ", ".join(filter(None, address_components))

    author = profile.first_name if profile else ""
    if not profile:
        print("story.other_params.get('user_name', ''): ", story.other_params.get('user_name', ''))
        print("story.other_params.get('location', ''): ", story.other_params.get('location', ''))
        author = story.other_params.get('user_name', '') if story.other_params else ''
        address_string = story.other_params.get('location', '') if story.other_params else ''
    print("Author: ", author)
    print("address_string: ", address_string)
    if story and story.language and story.language != 'en':
        if author:
            author = translate_field(
                voice_provider=voice_provider, message_body=author, target_language=story.language
            )
        if address_string:
            address_string = translate_field(
                voice_provider=voice_provider, message_body=address_string, target_language=story.language
            )
    return author, address_string, company_logo
