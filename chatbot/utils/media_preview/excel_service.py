from chatbot.utils.knowledge_service.reports_utils import generate_xlsx_from_json
from chatbot.utils.S3.s3_service import upload_media


def handle_duplicate_links(sources_list: list) -> list:
    """
    Removes duplicate sources.
    - If source is dict → dedupe by URL
    - If source is string → dedupe by full string
    """
    if not sources_list or not isinstance(sources_list, list):
        return []

    seen = set()
    unique_sources = []

    for source in sources_list:
        # Case 1: dict source (future / structured)
        if isinstance(source, dict):
            key = source.get("url")
            if key and key not in seen:
                seen.add(key)
                unique_sources.append(source)

        # Case 2: string source (current working behaviour)
        elif isinstance(source, str):
            key = source.strip()
            if key and key not in seen:
                seen.add(key)
                unique_sources.append(source)

    return unique_sources


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
    # ✅ NEW: handle duplicate links (PDF-aligned)
    cleaned_sources = handle_duplicate_links(sources_list)

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
        "Sources": cleaned_sources,
    }

    excel_file = generate_xlsx_from_json(excel_data)

    excel_filename = f"{project_title}.xlsx" if project_title else "Project_Report.xlsx"
    excel_filename = "".join(
        c for c in excel_filename if c.isalnum() or c in (" ", "-", "_", ".")
    ).replace(" ", "_")

    return {
        "file": excel_file,
        "file_name": excel_filename,
    }


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
