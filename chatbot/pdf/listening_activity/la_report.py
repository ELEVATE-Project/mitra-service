from chatbot.models import StoryTranslation


def get_common_report_html(story, profile):
    # Get data from other_params
    other_params = story.other_params or {}
    question_answers = other_params.get('question_answers', [])
    block = other_params.get('block', '')
    district = other_params.get('district', '')
    company_logo = other_params.get('company_logo', '')

    # Build location string
    location_parts = [part for part in [block, district] if part]
    location_string = ", ".join(location_parts)

    # Build questions and answers HTML
    qa_html = ""
    for i, qa in enumerate(question_answers, 1):
        if isinstance(qa, dict) and qa.get('question') and qa.get('answer'):
            qa_html += f"""
            <div class="qa-section">
                <div class="question-number">{i}.</div>
                <div class="question-text">{clean_escaped_text(qa['question'])}</div>
                <div class="answer-arrow">→</div>
                <div class="answer-text">{clean_escaped_text(qa['answer'])}</div>
            </div>
            """

    page_html = f"""
    <div class="qa-report-container">
        <div class="qa-header">
            <div class="qa-location">{location_string}</div>
            {f'<img src="{company_logo}" class="qa-logo" alt="Company Logo">' if company_logo else ''}
        </div>

        <div class="qa-title">{story.title}</div>

        <div class="qa-content">
            {qa_html}
        </div>
    </div>
    """
    return page_html


def clean_escaped_text(text):
    if not text:
        return ""
    text = str(text).replace("\\'", "'")  # \'  →  '
    text = text.replace('\\"', '"')  # \"  →  "
    text = text.replace("\\\\", "\\")  # \\  →  \
    return text.strip()


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
