import re
import json_repair
from chatbot.pdf.shiksha_chaupal.story_images_page import get_report_images_page_html
from chatbot.utils.story_llama_utils import translate_field
from datetime import datetime


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

    challenges_char_limit = translation_json.get('challenges_char_limit', None)
    first_challenges_char_limit = translation_json.get('first_challenges_char_limit', None)
    solutions_char_limit = translation_json.get('solutions_char_limit', None)

    challenges_html = process_steps(
        raw_data=challenges_faced,
        fallback_text=translation_json.get('no_challenges_faced_text', ""),
        heading=translation_json.get('heading2', "Challenges"),
        char_limit=challenges_char_limit,
        first_char_limit=first_challenges_char_limit,
        is_challenges=True  # New flag
    )

    solutions_html = process_steps(
        raw_data=solutions_discussed, fallback_text=translation_json.get('no_solutions_text', ""),
        heading=translation_json.get('heading3', "Solutions"), char_limit=solutions_char_limit
    )

    author, address_string, company_logo, date_of_discussion, number_of_people = get_user_details(
        story=story, profile=profile, voice_provider=voice_provider
    )
    # info_parts = []
    if date_of_discussion and date_of_discussion != '':
        info_html = f"<p style='text-align: center'>{translation_json.get('dateHeader', '')}: {date_of_discussion}<p>"
    # info_html = f"<p>{' &nbsp;&nbsp; '.join(info_parts)}</p>" if info_parts else ''
    else:
        info_html=''
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
        <p>{author if author else ""}</p>
        <p>{address_string}</p>
         {info_html}
       
        {challenges_html if challenges_faced not in [None, [], [""]] else ""}
        {solutions_html if solutions_discussed not in [None, [], [""]] else ""}
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


def process_steps(raw_data, fallback_text, char_limit, first_char_limit=None, heading=None, is_challenges=False):
    if isinstance(raw_data, str):
        try:
            if raw_data.strip().startswith("["):
                raw_data = json_repair.repair_json(raw_data, return_objects=True)
            else:
                raw_data = [raw_data]
        except Exception as e:
            raw_data = [fallback_text]

    steps = (
        [clean_escaped_text(step) for step in raw_data] if isinstance(raw_data, list)
        else [clean_escaped_text(raw_data)] if isinstance(raw_data, str)
        else [fallback_text]
    )

    if steps and isinstance(steps, list) and len(steps) == 1 and isinstance(steps[0], str):
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

    # Determine chunking logic
    chunks = []
    current_chunk = []
    current_length = 0
    chunk_index = 0

    for step in split_steps:
        current_limit = first_char_limit if is_challenges and chunk_index == 0 else char_limit or 1200
        step_len = len(step)

        if current_length + step_len > current_limit and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [step]
            current_length = step_len
            chunk_index += 1
        else:
            current_chunk.append(step)
            current_length += step_len

    if current_chunk:
        chunks.append(current_chunk)

    # Build HTML with page breaks between chunks
    full_html = ""
    current_number = 1  # Counter to maintain numbering across chunks
    for i, chunk in enumerate(chunks):
        # Do not apply page-break to the last chunk
        page_break = "split-div1" if i < len(chunks) - 1 else ""
        # Only add page break if it's not the last chunk
        html = (
                # f" <div class='second-main-sec-div {page_break}'> <div class='story-second-page-section'>" +
                f"<div class='{page_break}'>"
                f"<div class='second-main-sec-div'>"
                f"<div class='story-second-page-section'>"
                "<div class='split-div'>"
                + (f"<h2>{heading}</h2>" if heading else "")
                + "<ol class='secondpage-order-list'>"
                + ''.join(f"<li>{current_number + idx}. {step}</li>" for idx, step in enumerate(chunk))
                + "</ol></div></div></div></div>"
        )
        full_html += html
        # Update the current_number after the chunk
        current_number += len(chunk)

    return full_html or fallback_text


def get_user_details(story, profile, voice_provider):
    profile_addresses=None
    if profile and profile.first_name:
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

    author = profile.first_name if profile and profile.first_name else ""
    if not profile or not profile.first_name:
        print("story.other_params.get('user_name', ''): ", story.other_params.get('user_name', ''))
        print("story.other_params.get('location', ''): ", story.other_params.get('location', ''))
        author = story.other_params.get('user_name', '') if story.other_params else ''
        address_string = story.other_params.get('location', '') if story.other_params else ''
    print("Author: ", author)
    print("address_string: ", address_string)
    if story and story.language and story.language != 'en':
        if author and author not in ["None", None]:
            author = translate_field(
                voice_provider=voice_provider, message_body=author, target_language=story.language
            )
        if address_string:
            address_string = translate_field(
                voice_provider=voice_provider, message_body=address_string, target_language=story.language
            )
    date_of_discussion = story.other_params.get('discussion_date', None)
    date_of_discussion = format_date_to_ddmmyyyy(date_of_discussion)
    print("date_of_discussion: ", date_of_discussion)
    number_of_people = story.other_params.get('participants_count', None)
    print("number_of_people: ", number_of_people)

    return author, address_string, company_logo, date_of_discussion, number_of_people


def format_date_to_ddmmyyyy(date_value):
    if isinstance(date_value, datetime):
        return date_value.strftime("%d/%m/%Y")
    elif isinstance(date_value, str):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_value, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
    return ""
