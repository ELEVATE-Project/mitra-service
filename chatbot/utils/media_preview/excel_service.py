from chatbot.utils.knowledge_service.reports_utils import generate_xlsx_from_json
from chatbot.utils.S3.s3_service import upload_media


# ============================
# 1. GENERATE EXCEL (PURE)
# ============================

def generate_excel_file(
    *,
    project_title: str,
    author_name: str,
    location: str,
    timeline: str,
    user_problem_statement: str,
    project_objective: str,
    user_action_steps,
    sources_list: list,
):
    """
    Generates Excel file and returns file + filename.
    """

    excel_data = {
        "Project Title": project_title,
        "Author": author_name,
        "Location": location,
        "Timeline": timeline,
        "Problem Statement": user_problem_statement,
        "Objective": project_objective,
        "Action Steps": (
            "\n".join(user_action_steps)
            if isinstance(user_action_steps, list)
            else user_action_steps
        ),
        "Sources": sources_list,
    }

    excel_file = generate_xlsx_from_json(excel_data)

    excel_filename = f"{project_title}.xlsx" if project_title else "Project_Report.xlsx"
    excel_filename = "".join(
        c for c in excel_filename if c.isalnum() or c in (" ", "-", "_", ".")
    ).replace(" ", "_")

    # ✅ This is what your senior meant by “return the file here”
    return {
        "file": excel_file,
        "file_name": excel_filename,
    }


# ============================
# 2. GENERATE + UPLOAD (ORCHESTRATOR)
# ============================

def generate_and_upload_excel(
    *,
    project_id: int,
    project_title: str,
    author_name: str,
    location: str,
    timeline: str,
    user_problem_statement: str,
    project_objective: str,
    user_action_steps,
    sources_list: list,
):
    """
    Orchestrates Excel generation and upload.
    Returns media array (PDF + Excel compatible).
    """

    excel_generation_result = generate_excel_file(
        project_title=project_title,
        author_name=author_name,
        location=location,
        timeline=timeline,
        user_problem_statement=user_problem_statement,
        project_objective=project_objective,
        user_action_steps=user_action_steps,
        sources_list=sources_list,
    )

    excel_media = upload_media(
        project_id=project_id,
        media_type="excel",
        file_name=excel_generation_result["file_name"],
        file_content=excel_generation_result["file"].read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if not excel_media:
        return []

    return [excel_media]






# def generate_and_upload_excel(
#     *,
#     project_id: int,
#     project_title: str,
#     author_name: str,
#     location: str,
#     timeline: str,
#     user_problem_statement: str,
#     project_objective: str,
#     user_action_steps,
#     sources_list: list,
#     folder_structure: str = "shikshagraha_commons/",
# ):
#     """
#     Generates Excel file, uploads it to S3, updates Project.other_params,
#     and returns excel metadata.
#     """

#     excel_data = {
#         "Project Title": project_title,
#         "Author": author_name,
#         "Location": location,
#         "Timeline": timeline,
#         "Problem Statement": user_problem_statement,
#         "Objective": project_objective,
#         "Action Steps": (
#             "\n".join(user_action_steps)
#             if isinstance(user_action_steps, list)
#             else user_action_steps
#         ),
#         "Sources": sources_list,
#     }

#     excel_content = generate_xlsx_from_json(excel_data)

#     excel_filename = f"{project_title}.xlsx" if project_title else "Project_Report.xlsx"
#     excel_filename = "".join(
#         c for c in excel_filename if c.isalnum() or c in (" ", "-", "_", ".")
#     ).replace(" ", "_")
#     # return them here

#     excel_key = upload_file_to_s3(
#         file_name=excel_filename,
#         file_content=excel_content.read(),
#         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#         project_id=project_id,
#         folder_structure=folder_structure,
#     )

#     if not excel_key:
#         return None

#     base = os.getenv("S3_MEDIA_URL")
#     excel_url = f"{base}{excel_key}"
    
#     # changes need to be made
#     Project.objects.filter(id=project_id).update(
#         other_params={
#             **(
#                 Project.objects.filter(id=project_id)
#                 .values_list("other_params", flat=True)
#                 .first()
#                 or {}
#             ),
#             "excel": {
#                 "url": excel_url,
#                 "file_name": excel_filename,
#             },
#         }
#     )
#     # return in a form of arrray both pdf and excel
#     return {
#         "url": excel_url,
#         "file_name": excel_filename,
#     }

