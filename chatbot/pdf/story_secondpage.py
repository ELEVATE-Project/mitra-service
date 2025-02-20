import re
from shikshalokam.models import Project


def get_story_secondpage_html(story):
    action_steps = (
        story.action_steps.split("\n") if isinstance(story.action_steps, str)
        else story.action_steps if isinstance(story.action_steps, list)
        else ["No action steps provided."]
    )
    project = Project.objects.filter(story=story).first()
    print("action step type: ", type(action_steps))
    print("action_steps: ", action_steps)
    steps = action_steps[0]
    split_steps = re.findall(r'(\d+\.\s*[^0-9]+)', steps.strip())
    split_steps = [step.strip() for step in split_steps if step.strip()]
    print("\n\nsplit_steps: ", split_steps)
    steps_html = (
            f"<ol style='list-style-type: none; padding: 0; margin: 0;'>"
            + ''.join(f"<li>{step}</li>" for step in split_steps)
            + "</ol>"
    )
    print("\n\nsteps_html: ", steps_html)

    page_html = f"""
    <div class="story-second-page-container page-break">
        <h1>Report of Micro Improvement</h1>
        <div class="story-second-page-section">
            <h2>Problem Statement</h2>
            <p>{project.problem_statement or "No problem statement provided."}</p>
        </div>
        <div class="story-second-page-section">
            <h2>Objective</h2>
            <p>{story.objective or "No objective provided."}</p>
        </div>
        <div class="story-second-page-section">
            <h2>Action Steps</h2>
            {steps_html}
        </div>
        <div class="story-second-page-section">
            <h2>Impact</h2>
            <p>{story.impact or "No impact provided."}</p>
        </div>
    </div>
    """
    return page_html
