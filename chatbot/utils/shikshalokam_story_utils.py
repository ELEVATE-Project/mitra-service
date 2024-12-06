import os
import traceback
import requests


base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def save_shikshalokam_story(story, problem_statement, chat_history, access_token, project_id, session):
    try:
        upload_response_json = {} #upload_to_cloud(session_value=session, access_token=access_token, story=story)
        attachments = upload_response_json.get('attachments')
        print("attachments: ", attachments)

        pdf_information = upload_response_json.get('pdfInformation')
        print("pdf_information: ", pdf_information)


        request_body = {
            "story": {
                "title": story.title,
                "problemStatement": problem_statement,
                "objective": story.objective,
                "timeline": "",
                "actionSteps": story.action_steps or [],
                "resources": [],
                "impact": story.impact,
                "summary": story.content,
                "authorName": story.author.first_name if story.author else "",
                "location": story.location or "",
                "conversation": [],
                "chatHistory": chat_history,
                "attachments": attachments,
                "pdfInformation": pdf_information,
            }
        }
        print("request_body: ", request_body)

        url = f"https://{base_url}/project/userProjects/addStory/{project_id}"

        headers = {
            "X-auth-token": access_token,
        }

        response = requests.post(url, headers=headers, json=request_body)
        response.raise_for_status()

        print(f"Story successfully saved to Shikshalokam: {response.status_code}")
    except Exception as e:
        traceback.print_exc()
        print(f"Failed to save story to Shikshalokam: {str(e)}")
