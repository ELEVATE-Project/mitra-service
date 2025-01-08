import traceback
import os
import requests
from shikshalokam.models import Task

base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def update_project_status_utils(project_id, access_token, flow):
    try:
        if flow == 'login':
            return {'message': 'This api has no effect in the current flow', 'status': 200}

        url = f"https://{base_url}/userProjects/update/{project_id}"
        print("using url: ", url)
        headers = {
            "X-auth-token": access_token,
        }

        request_body = {
            "reflectionStatus": "completed"
        }

        response = requests.post(url, headers=headers, json=request_body)
        print("response: ", response.json())

        return response.json()

    except Exception as e:
        traceback.print_exc()
        print(f"Failed to update project status: {str(e)}")


def get_project_formatted_data(user_project):
    tasks = Task.objects.filter(project=user_project)
    task_names = [task.task_name for task in tasks]
    task_names_str = ', '.join(task_names)

    project_data = {
        'problem_statement': user_project.expected_problem_statement,
        'objective': user_project.expected_objective,
        'action_steps': task_names_str,
        'duration': user_project.expected_duration + " week"
    }
    print("Using project data: ", project_data)

    return project_data
