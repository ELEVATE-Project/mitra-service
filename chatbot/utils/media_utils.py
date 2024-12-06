import os
import requests
from chatbot.models import StoryMedia, MediaTypeChoices
from django.db.models import Q


base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def upload_to_cloud(session_value, access_token, story=None, instance=None):
    url = f"https://{base_url}/project/v1/cloud-services/files/preSignedUrls"
    headers = {"X-auth-token": access_token}

    if story:
        file_names = StoryMedia.objects.filter(
            story=story,
            media_type=MediaTypeChoices.PDF
        )
        data = {
            "request": {
                session_value: {
                    "files": [file.name for file in file_names]
                }
            }
        }
    elif instance:
        if not instance.get('include_in_story') and not instance.get('media_type') == MediaTypeChoices.PDF:
            return
        print("instance len: ", len(instance))
        data = {
            "request": {
                session_value: {
                    "files": [instance.get('name')]
                }
            }
        }
    else:
        file_names = StoryMedia.objects.filter(
            Q(story__session=session_value, include_in_story=True) |
            Q(story__session=session_value, media_type=MediaTypeChoices.PDF)
        )
        data = {
            "request": {
                session_value: {
                    "files": [file.name for file in file_names]
                }
            }
        }

    print("data: ", data)

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print("response: ", response)
        json_response = response.json()
        results = json_response.get("result", {})
        print("results: ", results)

        attachments = []
        pdf_information = []

        if story:
            for file_info in results.get(session_value, {}).get("files", []):
                source_path = file_info["payload"]["sourcePath"]
                pdf_information.append({
                    "filePath": source_path,
                    "language": story.language
                })

                with open(source_path, "rb") as file_data:
                    upload_response =requests.put(
                        file_info["url"],
                        data=file_data,
                        headers={"Content-Type": "application/octet-stream"}
                    )
                    if upload_response.status_code == 200:
                        print(f"File uploaded successfully")
                    else:
                        print(
                            f"Failed to upload file: {upload_response.status_code}, "
                            f"{upload_response.text}"
                        )

            return {"attachments": [], "pdfInformation": pdf_information}

        if instance:
            file_name = instance.get('name')
            file_info = results.get(session_value, {}).get("files", [])[0]
            source_path = file_info["payload"]["sourcePath"]
            file_data = instance.get('file')
            upload_response = requests.put(
                file_info["url"],
                data=file_data,
                headers={"Content-Type": "application/octet-stream"}
            )
            if upload_response.status_code == 200:
                print(f"File uploaded successfully: {file_name}")
            else:
                print(f"Failed to upload file {file_name}: {upload_response.status_code}, {upload_response.text}")

            # with open(source_path, "rb") as file_data:
            #     requests.put(
            #         file_info["url"],
            #         data=file_data,
            #         headers={"Content-Type": "application/octet-stream"}
            #     )
            return {
                "attachments": [
                    {"name": file_name, "sourcePath": source_path, "type": instance.get('media_type')}
                ],
                "pdfInformation": []
            }

        for session_id, session_data in results.items():
            if session_id == "cloudStorage":
                continue
            for file_info in session_data.get("files", []):
                file_name = file_info["file"]
                presigned_url = file_info["url"]
                source_path = file_info["payload"]["sourcePath"]

                if not os.path.exists(source_path):
                    continue

                media_type = StoryMedia.objects.filter(name=file_name).first().media_type
                attachments.append({
                    "name": file_name,
                    "sourcePath": source_path,
                    "type": media_type,
                })

                if file_name.lower().endswith(".pdf"):
                    pdf_information.append({
                        "filePath": source_path,
                        "language": StoryMedia.objects.filter(name=file_name).first().story.language
                    })

                with open(source_path, "rb") as file_data:
                    upload_response = requests.put(
                        presigned_url,
                        data=file_data,
                        headers={"Content-Type": "application/octet-stream"}
                    )
                    if upload_response.status_code == 200:
                        print(f"File uploaded successfully")
                    else:
                        print(
                            f"Failed to upload file: {upload_response.status_code}, "
                            f"{upload_response.text}"
                        )
        json_val = {"attachments": attachments, "pdfInformation": pdf_information}
        print("json_val: ", json_val)
        return {"attachments": attachments, "pdfInformation": pdf_information}

    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None
