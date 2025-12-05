import re
import logging
import json_repair
from jinja2 import Template
from chatbot.models import PDFTemplates
from chatbot.pdf.shiksha_chaupal.story_images_page import get_report_images_page_html
from datetime import datetime

logger = logging.getLogger('django')


def render_template_from_db(template_name, context):
    """
    Fetch and render Jinja2 template from PDFTemplates database.
    Falls back to hardcoded HTML if template not found.
    
    Args:
        template_name: Name of the template in PDFTemplates model
        context: Dictionary of variables to render in template
    
    Returns:
        Rendered HTML string
    """
    try:
        
        # Fetch template from database
        pdf_template = PDFTemplates.objects.get(template_name=template_name)
        
        logger.info(f"[PDF TEMPLATE] ✓ Template found in database!")
        
        # Merge constants_json into context if available
        if pdf_template.constants_json:
            # Constants from DB have lower priority than runtime context
            merged_context = {**pdf_template.constants_json, **context}
        else:
            merged_context = context
        
        logger.info(f"[PDF TEMPLATE]   - Context keys: {list(merged_context.keys())}")
        
        # Render Jinja2 template
        logger.info(f"[PDF TEMPLATE] Rendering Jinja2 template...")
        template = Template(pdf_template.template)
        html_content = template.render(**merged_context)
        
        logger.info(f"[PDF TEMPLATE] ✓✓✓ SUCCESS! Rendered template from DATABASE (Jinja2)")
        print(f"\n{'='*80}")
        print(f"✓ PDF GENERATION: Using DATABASE JINJA2 TEMPLATE")
        print(f"  Template: {template_name}")
        print(f"  User Type: {pdf_template.user_type}")
        print(f"{'='*80}\n")
        
        return html_content
        
    except PDFTemplates.DoesNotExist:
        logger.warning(f"[PDF TEMPLATE] ✗ Template '{template_name}' NOT FOUND in database")
        logger.warning(f"[PDF TEMPLATE] ⚠ FALLING BACK to hardcoded HTML generation")
        print(f"\n{'='*80}")
        print(f"⚠ PDF GENERATION: Using FALLBACK HARDCODED HTML")
        print(f"  Reason: Template '{template_name}' not found in database")
        print(f"  Action: Create PDFTemplate record to use Jinja2 templates")
        print(f"{'='*80}\n")
        
        # Fallback to legacy hardcoded HTML generation
        return get_mom_report_html_legacy(
            story=context.get('story'),
            story_vernacular=context.get('story_vernacular'),
            voice_provider=context.get('voice_provider'),
            profile=context.get('profile'),
            translation_json=context.get('translation_json'),
            challenges_faced=context.get('challenges_faced'),
            solutions_discussed=context.get('solutions_discussed'),
            remarks=context.get('remarks')
        )
    except Exception as e:
        logger.error(f"[PDF TEMPLATE] ✗✗✗ ERROR rendering template '{template_name}'")
        logger.error(f"[PDF TEMPLATE]   - Error: {str(e)}")
        logger.error(f"[PDF TEMPLATE]   - Error type: {type(e).__name__}")
        logger.warning(f"[PDF TEMPLATE] ⚠ FALLING BACK to hardcoded HTML generation")
        print(f"\n{'='*80}")
        print(f"✗ PDF GENERATION: Using FALLBACK HARDCODED HTML")
        print(f"  Reason: Template rendering error")
        print(f"  Error: {str(e)}")
        print(f"{'='*80}\n")
        
        # Fallback to legacy hardcoded HTML generation on any error
        return get_mom_report_html_legacy(
            story=context.get('story'),
            story_vernacular=context.get('story_vernacular'),
            voice_provider=context.get('voice_provider'),
            profile=context.get('profile'),
            translation_json=context.get('translation_json'),
            challenges_faced=context.get('challenges_faced'),
            solutions_discussed=context.get('solutions_discussed'),
            remarks=context.get('remarks')
        )


def get_mom_report_html(story, story_vernacular, voice_provider, profile):
    """
    Generate MOM (Minutes of Meeting) report HTML using database-driven Jinja2 templates.
    Falls back to legacy hardcoded HTML if template not found.
    """
    logger.info(f"[PDF GENERATION] Starting MOM PDF generation for story: '{story.title if story else 'Unknown'}'")
    
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

    # Process chunks for template rendering
    challenges_chunks = process_steps_to_chunks(
        raw_data=challenges_faced,
        fallback_text=translation_json.get('no_challenges_faced_text', ""),
        char_limit=challenges_char_limit,
        first_char_limit=first_challenges_char_limit,
        is_challenges=True
    )

    solutions_chunks = process_steps_to_chunks(
        raw_data=solutions_discussed,
        fallback_text=translation_json.get('no_solutions_text', ""),
        char_limit=solutions_char_limit
    )

    remarks_chunks = process_steps_to_chunks(
        raw_data=remarks,
        fallback_text=translation_json.get('no_remarks_text', ""),
        char_limit=remarks_char_limit
    )

    author, address_string, company_logo, date_of_discussion, participants_info, organization = get_user_details(
        story=story, profile=profile, voice_provider=voice_provider, translation_json=translation_json
    )

    if hasattr(story, 'story'):
        story_obj = story.story
    else:
        story_obj = story

    # Get images HTML
    images_html = get_report_images_page_html(story=story_obj)

    # Build context dictionary for template rendering
    context = {
        'story': story,
        'story_vernacular': story_vernacular,
        'voice_provider': voice_provider,
        'profile': profile,
        'translation_json': translation_json,
        'challenges_faced': challenges_faced,
        'solutions_discussed': solutions_discussed,
        'remarks': remarks,
        'challenges_chunks': challenges_chunks,
        'solutions_chunks': solutions_chunks,
        'remarks_chunks': remarks_chunks,
        'story_title': story.title,
        'author': author if author else "",
        'organization': organization,
        'address_string': address_string,
        'date_of_discussion': date_of_discussion,
        'participants_info': participants_info,
        'company_logo': company_logo,
        'images_html': images_html,
        'heading_challenges': translation_json.get('heading2', 'Challenges'),
        'heading_solutions': translation_json.get('heading3', 'Solutions'),
        'heading_remarks': translation_json.get('heading4', 'Remarks'),
        'dateHeader': translation_json.get('dateHeader', 'Date of discussion'),
    }

    logger.info(f"[PDF GENERATION] Calling render_template_from_db for MOM report...")
    
    # Generate HTML content using database template (with fallback to legacy)
    html_content = render_template_from_db(
        template_name='chaupal_mom_report',
        context=context
    )
    
    logger.info(f"[PDF GENERATION] ✓ MOM PDF HTML generation complete, length: {len(html_content)} characters")
    
    return html_content


def get_mom_report_html_legacy(story, story_vernacular, voice_provider, profile, 
                                translation_json=None, challenges_faced=None, 
                                solutions_discussed=None, remarks=None):
    """
    LEGACY FALLBACK FUNCTION - Use render_template_from_db() instead.
    Generate MOM report HTML using hardcoded HTML generation.
    This function is kept for backward compatibility and as fallback.
    """
    logger.info(f"[PDF GENERATION] Using LEGACY hardcoded HTML generation")
    
    # Recompute if not provided
    if translation_json is None:
        translation_json = story_vernacular.translation_json
        if translation_json:
            translation_json = translation_json.get('second_page', {})
        else:
            translation_json = {}
    
    if challenges_faced is None or solutions_discussed is None or remarks is None:
        if story.other_params:
            challenges_faced = story.other_params.get('challenges_faced')
            solutions_discussed = story.other_params.get('solutions_discussed')
            remarks = story.other_params.get('remarks')
        else:
            challenges_faced, solutions_discussed, remarks = None, None, None

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
        is_challenges=True
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
    participants_html = f"<p>{participants_info}</p>" if participants_info else ""

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


def process_steps_to_chunks(raw_data, fallback_text, char_limit, first_char_limit=None, is_challenges=False):
    """
    Process steps data and return chunks for template rendering.
    Similar to process_steps() but returns structured data instead of HTML.
    """
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

    return chunks if chunks else [[fallback_text]]


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
    """Format participants count showing only non-zero values and include total."""
    if not participants_count or not isinstance(participants_count, dict):
        return None

    def safe_int(value):
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0

    participant_parts = []
    print("participants_count: ", participants_count)
    total = safe_int(participants_count.get('total'))

    # Get labels from translation_json (fallbacks if not present)
    women_label = translation_json.get('womenLabel', 'Women')
    men_label = translation_json.get('menLabel', 'Men')
    children_label = translation_json.get('childrenLabel', 'Children')

    # Women
    women_count = safe_int(participants_count.get('women'))
    if women_count > 0:
        participant_parts.append(f"{women_count}{women_label.lower()}")

    # Men
    men_count = safe_int(participants_count.get('men'))
    if men_count > 0:
        participant_parts.append(f"{men_count}{men_label.lower()}")

    # Children
    children_count = safe_int(participants_count.get('children'))
    if children_count > 0:
        participant_parts.append(f"{children_count}{children_label.lower()}")

    if not participant_parts and total <= 0:
        return None
    participants_label=translation_json.get('memberHeader', 'Total Participants')
    return f"{participants_label}: {total}" if not participant_parts else f"{participants_label}: {total} [{', '.join(participant_parts)}]"


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
