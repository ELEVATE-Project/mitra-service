from chatbot.models import Profile
from shikshalokam.models import Project, Category, ProjectTemplate, Task
from django.db import transaction


def update_project_in_db(project_data):
    if project_data:
        project_id = project_data.get("_id")
        if project_id:
            try:
                with transaction.atomic():
                    current_project = Project.objects.get(project_id=project_id)

                    categories = project_data.get("categories")
                    category_map = {}
                    if categories:
                        for category_data in categories:
                            category_id = category_data.get("_id")
                            if category_id:
                                category, _ = Category.objects.update_or_create(
                                    category_id=category_id,
                                    defaults={'name': category_data.get("name")}
                                )
                                category_map[category_id] = category

                    project_template_id = project_data.get("projectTemplateId")
                    if project_template_id:
                        project_template_defaults = {
                            'title': project_data.get('templateTitle'),
                            'description': project_data.get('templateDescription'),
                        }

                        if 'categoryId' in project_data:
                            category_id = project_data['categoryId']
                            project_template_defaults['category'] = category_map.get(category_id)

                        project_template, _ = ProjectTemplate.objects.update_or_create(
                            template_id=project_template_id,
                            defaults=project_template_defaults
                        )

                    current_project.project_status = project_data.get('status', current_project.project_status)
                    current_project.recommended_for = project_data.get('recommendedFor',
                                                                       current_project.recommended_for)
                    current_project.expected_title = project_data.get('title', current_project.expected_title)
                    current_project.program_id = project_data.get('programId', current_project.program_id)
                    current_project.program_name = project_data.get(
                        'programInformation', {}).get("name", current_project.program_name)

                    if project_template_id:
                        current_project.project_template = project_template

                    current_project.save()

                    tasks = project_data.get("tasks")
                    if tasks:
                        for task_data in tasks:
                            task_id = task_data.get("_id")
                            if task_id:
                                Task.objects.update_or_create(
                                    task_id=task_id,
                                    project=current_project,
                                    defaults={
                                        'task_name': task_data.get("name"),
                                        'task_status': task_data.get("status"),
                                        'description': task_data.get("description"),
                                    }
                                )

                print("Categories, template, project, and tasks updated successfully.")
            except Project.DoesNotExist:
                print(f"Project with ID {project_id} does not exist.")
            except Exception as e:
                print(f"An error occurred: {str(e)}")


def update_profile_in_db(profile_data, user_id):
    if not user_id or not profile_data:
        return
    try:
        current_profile = Profile.objects.get(userid=user_id)

        if profile_data and current_profile:
            current_profile.email = profile_data.get('email', current_profile.email)
            current_profile.name = profile_data.get('name', current_profile.name)
            current_profile.preferred_language = (
                profile_data.get('preferred_language', {}).get('value', current_profile.preferred_language)
            )
            current_profile.organization = profile_data.get('organization', {}).get('name', current_profile.organization)
            current_profile.block = profile_data.get('block', {}).get('label', current_profile.block)
            current_profile.state = profile_data.get('state', {}).get('label', current_profile.state)
            current_profile.district = profile_data.get('district', {}).get('label', current_profile.district)
            current_profile.designation = profile_data.get('user_roles', current_profile.designation)

            current_profile.save()

    except Profile.DoesNotExist:
        print(f"Profile with ID {user_id} does not exist.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
