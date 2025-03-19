import re

from chatbot.pdf.story_secondpage import clean_escaped_text
from shikshalokam.models import Project
import json_repair


def get_story_secondpage_html_kannada(story):
    print("story.action_steps: ", story.action_steps)
    if isinstance(story.action_steps, str):
        try:
            if story.action_steps.strip().startswith("["):
                story.action_steps = json_repair.repair_json(story.action_steps, return_objects=True)
                print("story.action_steps after repair: ", story.action_steps)
            else:
                story.action_steps = [story.action_steps]
        except Exception as e:
            print(f"Error repairing JSON: {e}")
            story.action_steps = ["ಯಾವುದೇ ಕ್ರಮ ಕ್ರಮಗಳನ್ನು ಒದಗಿಸಲಾಗಿಲ್ಲ."]

    action_steps = (
        [clean_escaped_text(step) for step in story.action_steps] if isinstance(story.action_steps, list)
        else [clean_escaped_text(story.action_steps)] if isinstance(story.action_steps, str)
        else ["ಯಾವುದೇ ಕ್ರಮ ಕ್ರಮಗಳನ್ನು ಒದಗಿಸಲಾಗಿಲ್ಲ."]
    )
    project = Project.objects.filter(story=story).first()
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
            f"<ol style='list-style-type: none; padding: 0; margin: 0;'>"
            + ''.join(f"<li>{step}</li>" for step in split_steps)
            + "</ol>"
    )
    print("\n\nsteps_html: ", steps_html)
    print("story.objective: ", story.objective)

    page_html = f"""
    <div class="story-second-page-container">
        <h1>ಸೂಕ್ಷ್ಮ ಸುಧಾರಣೆಗಳ ವರದಿ</h1>
        <div class="story-second-page-section">
            <h2>ಸಮಸ್ಯೆಯ ವಿವರಣೆ</h2>
            <p>{project.actual_problem_statement or ""}</p>
        </div>
        <div class="story-second-page-section">
            <h2>ಉದ್ದೇಶ</h2>
            <p>{story.objective or "ಯಾವುದೇ ಉದ್ದೇಶವನ್ನು ಒದಗಿಸಲಾಗಿಲ್ಲ."}</p>
        </div>
        <div class="story-second-page-section story-action-steps">
            <h2>ಕ್ರಿಯೆಯ ಹಂತಗಳು</h2>
            {steps_html or "ಯಾವುದೇ ಕ್ರಮ ಕ್ರಮಗಳನ್ನು ಒದಗಿಸಿಲ್ಲ."}
        </div>
        <div class="story-second-page-section story-action-steps">
            <h2>ಪರಿಣಾಮ</h2>
            <p>{story.impact or "ಯಾವುದೇ ಪರಿಣಾಮ ಬೀರಲಿಲ್ಲ."}</p>
        </div>
    </div>
    """
    return page_html
