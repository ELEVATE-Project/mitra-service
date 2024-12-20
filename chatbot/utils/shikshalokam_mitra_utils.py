import os
import requests
from datetime import timedelta, timezone
from pydantic_core._pydantic_core import ValidationError
from django.utils.timezone import now
from chatbot.models import Profile, MitraProject
import json

from shikshalokam.models import Project, Task

base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def create_project_utils(
    access_token,
    user_problem_statement,
    project_title,
    project_duration_weeks,
    user_action_steps,
):
    url = f"https://{base_url}/userProjects/add"

    headers = {
        "X-auth-token": access_token,
    }
    start_date = now()
    start_date = start_date.astimezone(tz=timezone.utc)

    end_date = (start_date + timedelta(weeks=project_duration_weeks))

    start_date = start_date.isoformat()
    end_date = end_date.isoformat()

    request_body = {
        "program": {
            "conversation": [],
            "name": user_problem_statement,
            "startDate": start_date,
        },
        "projects": [
            {
                "duration": f"{project_duration_weeks} week",
                "endDate": end_date,
                "source": {
                    "apiVersion": "",
                    "confidenceScore": 0,
                    "info": {
                        "pageNo": "",
                        "title": "",
                        "url": ""
                    },
                    "model": "",
                    "provider": ""
                },
                "startDate": start_date,
                "status": "completed",
                "tasks": [
                    {
                        "isDeletable": False,
                        "name": step,
                    } for step in user_action_steps
                ],
                "title": project_title
            }
        ]
    }

    print("req body: ", request_body)

    try:
        response = requests.post(url, headers=headers, json=request_body)
        response.raise_for_status()
        json_response = response.json()
        print("json_response: ", json_response)

        if not json_response or "result" not in json_response:
            raise ValidationError("Invalid response from the API")

        program_id = json_response["result"].get("programId")
        project_id = json_response["result"].get('projects')[0].get("_id")

        return {
            "programId": program_id,
            "projectId": project_id
        }

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while making the API call: {e}")
        return None
    except ValueError as e:
        print(f"Validation error: {e}")
        return None


def create_mitra_project_utils(
        session, actual_problem_statement, project_title, project_duration,
        project_objective, user_action_steps, project_id, program_id, profile
):
    try:

        if isinstance(user_action_steps, str):
            user_action_steps = json.loads(user_action_steps)

        if not isinstance(user_action_steps, list):
            user_action_steps = []

        project = Project.objects.create(
            author=profile,
            actual_duration=project_duration,
            actual_title=project_title,
            actual_problem_statement=actual_problem_statement,
            actual_objective=project_objective,
            project_id=project_id,
            program_id=program_id
        )

        for action in user_action_steps:
            Task.objects.create(
                project=project,
                task_name=action
            )

        return {
            "status": "success",
            "message": "Project and Task created successfully",
            "project_id": project.id,
        }

    except Profile.DoesNotExist:
        return {"status": "error", "message": "Profile not found"}
    except Exception as e:
        return {"status": "error", "message": f"An error occurred: {str(e)}"}


def import_project_from_library_utils(access_token, program_name, project_template_id):
    url = f"https://{base_url}/userProjects/importFromLibrary/{project_template_id}"

    headers = {
        "X-auth-token": access_token,
    }

    request_body = {
        "programName": program_name
    }

    print("req body: ", request_body)

    try:
        response = requests.post(url, headers=headers, json=request_body)
        response.raise_for_status()
        json_response = response.json()
        print("json_response: ", json_response)

        if not json_response or "result" not in json_response:
            raise ValidationError("Invalid response from the API")

        return json_response

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while making the API call: {e}")
        return None
    except ValueError as e:
        print(f"Validation error: {e}")
        return None
