import re
import json_repair
from chatbot.pdf.shiksha_chaupal.story_images_page import get_report_images_page_html
from datetime import datetime


def get_mom_report_html(story, story_vernacular, voice_provider, profile):
    if story.other_params:
        challenges_faced = story.other_params.get('challenges_faced')
        solutions_discussed = story.other_params.get('solutions_discussed')
        remarks = story.other_params.get('remarks')
    else:
        challenges_faced, solutions_discussed, remarks = None, None, None

    translation_json = story_vernacular.translation_json
    if translation_json:
        translation_json = translation_json.get('second_page', {})
    else:
        translation_json = {}

    challenges_char_limit = translation_json.get('challenges_char_limit', None)
    first_challenges_char_limit = translation_json.get('first_challenges_char_limit', None)
    solutions_char_limit = translation_json.get('solutions_char_limit', None)
    remarks_char_limit = translation_json.get('remarks_char_limit', None)

    challenges_html = process_steps(
        raw_data=challenges_faced,
        fallback_text=translation_json.get('no_challenges_faced_text', ""),
        heading=translation_json.get('heading2', "Challenges"),
        char_limit=challenges_char_limit,
        first_char_limit=first_challenges_char_limit,
        is_challenges=True  # New flag
    )

    solutions_html = process_steps(
        raw_data=solutions_discussed,
        fallback_text=translation_json.get('no_solutions_text', ""),
        heading=translation_json.get('heading3', "Solutions"),
        char_limit=solutions_char_limit
    )

    remarks_html = process_steps(
        raw_data=remarks,
        fallback_text=translation_json.get('no_remarks_text', ""),
        heading=translation_json.get('heading4', "Remarks"),
        char_limit=remarks_char_limit
    )

    author, address_string, company_logo, date_of_discussion, participants_info, organization = get_user_details(
        story=story, profile=profile, voice_provider=voice_provider, translation_json=translation_json
    )

    # Build organization line
    organization_html = f"<p>{organization}</p>" if organization else ""

    # Build date line
    date_html = f"<p><span>{translation_json.get('dateHeader', 'Date of discussion')}:</span> {date_of_discussion}</p>" if date_of_discussion else ""

    # Build participants line
    participants_html = f"<p><span>{translation_json.get('memberHeader', 'Participants')}:</span> {participants_info}</p>" if participants_info else ""

    if hasattr(story, 'story'):
        story_obj = story.story
    else:
        story_obj = story

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
        {organization_html}
        <p>{address_string}</p>
        {date_html}
        {participants_html}

        {challenges_html if challenges_faced not in [None, [], [""]] else ""}
        {solutions_html if solutions_discussed not in [None, [], [""]] else ""}
        {remarks_html if remarks not in [None, [], [""], ""] else ""}
        {get_report_images_page_html(story=story_obj)}
    </div>
    """
    return page_html


def clean_escaped_text(text):
    text = text.replace("\\'", "")  # \'  →  '
    text = text.replace('\\"', '')  # \"  →  "
    text = text.replace("\\\\", "")  # \\  →  \
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


def format_participants_count(participants_count, translation_json):
    """Format participants count showing Men, Women, Children only if they have values"""
    if not participants_count or not isinstance(participants_count, dict):
        return None

    participant_parts = []

    # Get labels from translation
    women_label = translation_json.get('womenLabel', 'Women')
    men_label = translation_json.get('menLabel', 'Men')
    children_label = translation_json.get('childrenLabel', 'Children')

    # Add women count if exists and not empty
    women_count = participants_count.get('women', '').strip()
    if women_count:
        participant_parts.append(f"{women_label}{women_count}")

    # Add men count if exists and not empty
    men_count = participants_count.get('men', '').strip()
    if men_count:
        participant_parts.append(f"{men_label}{men_count}")

    # Add children count if exists and not empty
    children_count = participants_count.get('children', '').strip()
    if children_count:
        participant_parts.append(f"{children_label}{children_count}")

    return ', '.join(participant_parts) if participant_parts else None


def get_user_details(story, profile, voice_provider, translation_json):
    company_logo = translation_json.get('main_logo', '')
    print("logo: ", company_logo)

    author = profile.first_name if profile and profile.first_name else ""
    if not profile or not profile.first_name:
        author = story.other_params.get('user_name', '') if story.other_params else ''
    address_string = story.other_params.get('location', '') if story.other_params else ''

    date_of_discussion = story.other_params.get('discussion_date', None)
    date_of_discussion = format_date_to_ddmmyyyy(date_of_discussion)

    # Get organization
    organization = story.other_params.get('organization', '') if story.other_params else ''

    # Process participants count
    participants_count = story.other_params.get('participants_count', None) if story.other_params else None
    participants_info = format_participants_count(participants_count, translation_json)

    return author, address_string, company_logo, date_of_discussion, participants_info, organization


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
