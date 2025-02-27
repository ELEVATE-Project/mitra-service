import re
from shikshalokam.models import Project
import json_repair


def get_story_secondpage_html_hindi(story):
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
            story.action_steps = ["No action steps provided."]

    action_steps = (
        story.action_steps if isinstance(story.action_steps, list)
        else [story.action_steps] if isinstance(story.action_steps, str)
        else ["No action steps provided."]
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
    <div class="story-second-page-container page-break">
        <h1>सूक्ष्म सुधार की रिपोर्ट</h1>
        <div class="story-second-page-section">
            <h2>समस्या का विवरण</h2>
            <p>{project.actual_problem_statement or ""}</p>
        </div>
        <div class="story-second-page-section">
            <h2>उद्देश्य</h2>
            <p>{story.objective or "कोई उद्देश्य प्रदान नहीं किया गया."}</p>
        </div>
        <div class="story-second-page-section">
            <h2>कार्रवाई के चरण</h2>
            {steps_html or "कोई कार्रवाई चरण प्रदान नहीं किया गया."}
        </div>
        <div class="story-second-page-section">
            <h2>प्रभाव</h2>
            <p>{story.impact or "कोई प्रभाव नहीं पड़ा."}</p>
        </div>
    </div>
    """
    return page_html
