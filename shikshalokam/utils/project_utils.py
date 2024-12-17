import traceback
import os
import requests


base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def update_project_status_utils(project_id, access_token):
    try:
        url = f"https://{base_url}/userProjects/update/{project_id}"

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
