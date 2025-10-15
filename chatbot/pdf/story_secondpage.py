import re
import json_repair


def get_story_secondpage_html(story, project, story_vernacular):
    print("story.action_steps: ", story.action_steps)
    translation_json = story_vernacular.translation_json
    if translation_json:
        translation_json = translation_json.get('second_page', {})
    else:
        translation_json = {}

    if isinstance(story.action_steps, str):
        try:
            if story.action_steps.strip().startswith("["):
                story.action_steps = json_repair.repair_json(story.action_steps, return_objects=True)
                print("story.action_steps after repair: ", story.action_steps)
            else:
                story.action_steps = [story.action_steps]
        except Exception as e:
            print(f"Error repairing JSON: {e}")
            story.action_steps = [translation_json.get('no_action_step_text', "")]

    action_steps = (
        [clean_escaped_text(step) for step in story.action_steps] if isinstance(story.action_steps, list)
        else [clean_escaped_text(story.action_steps)] if isinstance(story.action_steps, str)
        else [translation_json.get('no_action_step_text', "")]
    )
    print("action step type: ", type(action_steps))
    print("action_steps: ", action_steps)
    # steps = action_steps[0]
    if action_steps and isinstance(action_steps, list) and len(action_steps) == 1 and isinstance(action_steps[0], str):
        steps_text = action_steps[0]
        split_steps = re.findall(r'\d+\.\s*[^0-9]+', steps_text)
        split_steps = [step.strip() for step in split_steps if step.strip()]
        if not split_steps:
            split_steps = action_steps
    elif action_steps and isinstance(action_steps, str):
        steps_text = " ".join(action_steps)
        split_steps = re.findall(r'\d+\.\s*[^.]+', steps_text)
        split_steps = [step.strip() for step in split_steps if step.strip()]
    else:
        split_steps = [step.strip() for step in action_steps if step.strip()]
    print("\n\nsplit_steps: ", split_steps)
    steps_html = (
            f"<ol style='list-style-type: decimal; padding: 0; margin: 0;'>"
            + ''.join(f"<li>{step}</li>" for step in split_steps)
            + "</ol>"
    )
    print("\n\nsteps_html: ", steps_html)
    print("story.objective: ", story.objective)
    if project:
        problem_statement = project.get('actual_problem_statement', '')
    elif story:
        problem_statement = story.other_params.get('problem_statement', '') if story and story.other_params else ''
    else:
        problem_statement = ''

    problem_statement = capitalize_first_letter(problem_statement)
    story.objective = capitalize_first_letter(story.objective or translation_json.get('no_objective_text', ""))
    story.impact = capitalize_first_letter(story.impact or translation_json.get('no_impact_text', ""))

    page_html = f"""
    <div class="story-second-page-container">
        <h1>{translation_json.get('heading1', "")}</h1>
        <div class="story-second-page-section">
            <h2>{translation_json.get('heading2', "")}</h2>
            <p>{problem_statement or translation_json.get('no_problem_statement_text', "")}</p>
        </div>
        <div class="story-second-page-section">
            <h2>{translation_json.get('heading3', "")}</h2>
            <p>{story.objective or translation_json.get('no_objective_text', "")}</p>
        </div>
        <div class="story-second-page-section story-action-steps">
            <h2>{translation_json.get('heading4', "")}</h2>
            {steps_html or translation_json.get('no_action_step_text', "")}
        </div>
        <div class="story-second-page-section story-action-steps">
            <h2>{translation_json.get('heading5', "")}</h2>
            <p>{story.impact or translation_json.get('no_impact_text', "")}</p>
        </div>
    </div>
    """
    return page_html


def clean_escaped_text(text):
    text = text.replace("\\'", "")# \'  →  '
    text = text.replace('\\"', '')# \"  →  "
    text = text.replace("\\\\", "") # \\  →  \
    print("Text: ", text)
    return text


def capitalize_first_letter(text):
    """Capitalize the first alphabetical character in the string, safely."""
    if not text:
        return text
    text = text.lstrip()
    if not text:
        return text
    return text[0].upper() + text[1:]
