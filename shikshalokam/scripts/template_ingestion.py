import json

from shikshalokam.models import Project, Evidence


def ingest_project_template(file_path):
    file_path = 'shikshalokam/scripts/projectTemplateJson.json'
    json_data = load_json(file_path)
    results = json_data.get('result')
    print(results[0].get('_id'))

    evidences = results[0].get('evidences')

    # Evidence.objects.

    Project.objects.get_or_create(
        project_id=results[0].get('_id'),
        defaults={
            "description": results[0].get('description'),
            "keywords": results[0].get('keywords'),
            "recommended_for": results[0].get('recommendedFor'),
            # "resource_name": results[0].get('keywords'),
            "actual_duration": results[0].get('metaInformation', {}).get('duration', None),
            "actual_problem_statement": results[0].get('problemStatement'),
            "actual_title": results[0].get('title'),
            "other_params": {'text': results[0].get('text')}, #store only if text there
            "categories": results[0].get('categories')
        }
    )


def load_json(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return data
