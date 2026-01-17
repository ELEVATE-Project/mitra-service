import json
import os
import uuid
import requests
from django.core.files.base import ContentFile
from chatbot.models import (
    CompanyBot, Media, KeyValue, Tag, Company
)
from chatbot.models.media_models import MediaImage, MediaTypeChoices
from django.conf import settings

ENABLE_SIMILARITY_CHECK = getattr(settings, 'BATCH_UPLOAD_ENABLE_SIMILARITY_CHECK', False)


def process_tags(tags_list):
    """Process and deduplicate tags"""
    seen = set()
    unique_tags = []

    for tag in tags_list:
        if isinstance(tag, dict):
            tag_name = tag.get('name', '')
        else:
            tag_name = str(tag)

        if tag_name and tag_name not in seen:
            seen.add(tag_name)
            unique_tags.append(tag_name)

    return unique_tags


def get_or_create_tags(tag_names):
    """Get or create Tag objects from tag names"""
    tag_objects = []
    for tag_name in tag_names:
        tag, created = Tag.objects.get_or_create(
            name=tag_name,
            defaults={'status': 'APPROVED', 'source_type': 'MANUAL'}
        )
        tag_objects.append(tag)
    return tag_objects


def save_media_from_export(media_data, company_bot):
    """
    Save media from exported data structure
    Maintains parent-child hierarchy
    Downloads file from S3 URL
    """
    filename = media_data.get('name', 'unknown')

    try:
        # Prepare tags
        tag_names = media_data.get('tags', [])
        unique_tags = process_tags(tag_names)

        # Get Company object by slug
        organization = None
        org_slug = media_data.get('organization', '')
        if org_slug:
            try:
                organization = Company.objects.get(slug=org_slug)
                print(f"Found organization: {organization.name} (slug: {org_slug})")
            except Company.DoesNotExist:
                print(f"Warning: Company with slug '{org_slug}' not found, setting organization to None")
                organization = None

        # Download file from S3 if URL exists
        file_content = None
        file_name = None
        file_url = media_data.get('file_url', '')

        if file_url:
            try:
                print(f"Downloading file from: {file_url}")
                response = requests.get(file_url, timeout=60)
                response.raise_for_status()
                file_content = response.content
                # Extract filename from URL
                file_name = file_url.split('/')[-1]
                print(f"Downloaded {len(file_content)} bytes as {file_name}")
            except Exception as e:
                print(f"Error downloading file: {e}")
                file_content = None
                file_name = None

        # Create parent Media object
        parent_media = Media(
            name=media_data.get('name', filename),
            media_type=media_data.get('media_type', MediaTypeChoices.TXT.value),
            description=media_data.get('description', ''),
            priority=media_data.get('priority', 'P1'),
            company_bot_id=company_bot.id,
            organization=organization,
            extracted_text=media_data.get('extracted_text', ''),
        )

        # Attach the file to the object BEFORE saving
        if file_content and file_name:
            file_obj = ContentFile(file_content)
            parent_media.file.save(file_name, file_obj, save=False)  # save=False to not trigger save yet
            print(f"Attached file: {file_name}")

        # Now save the parent media with all fields including file
        # Note: save() will trigger vector DB save automatically via the model's save method
        parent_media.save()
        print(f"Created parent Media object with ID: {parent_media.id}")
        print(f"Organization: {parent_media.organization}")
        print(f"File: {parent_media.file.name if parent_media.file else 'None'}")
        print(f"Note: Vector DB save will be triggered automatically by the save() method")

        # Set tags using ManyToMany relationship
        if unique_tags:
            tag_objects = get_or_create_tags(unique_tags)
            parent_media.tags.set(tag_objects)
            print(f"Saved {len(unique_tags)} tags")

        # Save key-values for parent
        key_values_to_create = []
        key_values_data = media_data.get('key_values', [])
        if key_values_data:
            for kv in key_values_data:
                if isinstance(kv, dict):
                    key_values_to_create.append(
                        KeyValue(
                            media=parent_media,
                            key=kv.get('key', ''),
                            value=kv.get('value', '')
                        )
                    )

        if key_values_to_create:
            KeyValue.objects.bulk_create(key_values_to_create)
            print(f"Saved {len(key_values_to_create)} key-value pairs for parent")

        # Save images for parent
        images_to_create = []
        images_data = media_data.get('images', [])
        if images_data:
            for img_data in images_data:
                if isinstance(img_data, dict):
                    images_to_create.append(
                        MediaImage(
                            media=parent_media,
                            image_url=img_data.get('image_url', ''),
                            caption=img_data.get('caption', '')
                        )
                    )

        if images_to_create:
            MediaImage.objects.bulk_create(images_to_create, ignore_conflicts=True)
            print(f"Saved {len(images_to_create)} images for parent")

        # Process subdocuments with parent-child hierarchy
        subdocuments_data = media_data.get('subdocuments', [])
        subdoc_count = 0
        subdoc_kv_count = 0
        subdoc_img_count = 0

        if subdocuments_data:
            print(f"Processing {len(subdocuments_data)} subdocuments...")

            subdocs_to_create = []
            for subdoc_data in subdocuments_data:
                if isinstance(subdoc_data, dict):
                    # Process subdocument tags
                    subdoc_tag_names = subdoc_data.get('tags', [])
                    unique_subdoc_tags = process_tags(subdoc_tag_names)

                    subdoc = Media(
                        name=subdoc_data.get('name', f"Subdoc of {filename}"),
                        media_type=subdoc_data.get('media_type', MediaTypeChoices.TXT.value),
                        description=subdoc_data.get('description', ''),
                        priority=media_data.get('priority', 'P1'),
                        company_bot_id=company_bot.id,
                        organization=organization,  # Use same organization as parent
                        extracted_text=subdoc_data.get('extracted_text', ''),
                        parent=parent_media  # PARENT-CHILD HIERARCHY MAINTAINED HERE
                    )
                    subdocs_to_create.append((subdoc, unique_subdoc_tags))

            # Bulk create subdocuments
            if subdocs_to_create:
                subdocs_only = [item[0] for item in subdocs_to_create]
                created_subdocs = Media.objects.bulk_create(subdocs_only)
                subdoc_count = len(created_subdocs)
                print(f"Created {subdoc_count} subdocuments with parent_id={parent_media.id}")

                # Set tags for subdocuments
                for i, subdoc in enumerate(created_subdocs):
                    subdoc_tags = subdocs_to_create[i][1]
                    if subdoc_tags:
                        tag_objects = get_or_create_tags(subdoc_tags)
                        subdoc.tags.set(tag_objects)

                # Now save key-values and images for each subdocument
                all_subdoc_kvs = []
                all_subdoc_images = []

                for i, subdoc in enumerate(created_subdocs):
                    subdoc_data = subdocuments_data[i]

                    # Key-values for subdocument
                    if subdoc_data.get('key_values'):
                        for kv in subdoc_data['key_values']:
                            if isinstance(kv, dict):
                                all_subdoc_kvs.append(
                                    KeyValue(
                                        media=subdoc,
                                        key=kv.get('key', ''),
                                        value=kv.get('value', '')
                                    )
                                )

                    # Images for subdocument
                    if subdoc_data.get('images'):
                        for img_data in subdoc_data['images']:
                            if isinstance(img_data, dict):
                                all_subdoc_images.append(
                                    MediaImage(
                                        media=subdoc,
                                        image_url=img_data.get('image_url', ''),
                                        caption=img_data.get('caption', '')
                                    )
                                )

                # Bulk create subdocument key-values
                if all_subdoc_kvs:
                    KeyValue.objects.bulk_create(all_subdoc_kvs)
                    subdoc_kv_count = len(all_subdoc_kvs)
                    print(f"Saved {subdoc_kv_count} key-value pairs for subdocuments")

                # Bulk create subdocument images
                if all_subdoc_images:
                    MediaImage.objects.bulk_create(all_subdoc_images, ignore_conflicts=True)
                    subdoc_img_count = len(all_subdoc_images)
                    print(f"Saved {subdoc_img_count} images for subdocuments")

        return {
            'success': True,
            'media_id': parent_media.id,
            'filename': filename,
            'message': f'Successfully saved {filename}',
            'parent_media_id': parent_media.id,
            'subdocument_count': subdoc_count,
            'parent_kv_count': len(key_values_to_create),
            'parent_image_count': len(images_to_create),
            'subdoc_kv_count': subdoc_kv_count,
            'subdoc_image_count': subdoc_img_count,
        }

    except Exception as e:
        print(f"Error saving {filename}: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'filename': filename,
            'message': f'Save failed: {str(e)}',
            'error': str(e)
        }


def batch_reingest_from_export(
    json_path,
    limit=None,
    start_index=0,
):
    """Re-ingest media from exported JSON file"""

    if not os.path.exists(json_path):
        raise ValueError(f"JSON file not found: {json_path}")

    try:
        company_bot = CompanyBot.objects.get(route="/tag_extractor")
    except CompanyBot.DoesNotExist:
        raise ValueError('CompanyBot with route "/tag_extractor" not found')

    # Load exported data
    with open(json_path) as f:
        items = json.load(f)

    # Apply offset and limit
    items = items[start_index:]
    if limit:
        items = items[:limit]

    total = len(items)
    session_id = str(uuid.uuid4())

    print("=" * 60)
    print(f"[Batch Re-ingest from Export] Started")
    print(f"[Batch Re-ingest from Export] Total items: {total}")
    print(f"[Batch Re-ingest from Export] Session ID: {session_id}")
    print("=" * 60)

    results = []

    for index, media_data in enumerate(items):
        filename = media_data.get('name', f'Media_{index}')
        print(f"\n[{index + 1}/{total}] Processing {filename}")

        try:
            print(f"Saving to database...")
            save_result = save_media_from_export(
                media_data=media_data,
                company_bot=company_bot
            )

            results.append(save_result)

            if save_result.get("success"):
                print(f"✓ Saved successfully - Parent Media ID: {save_result.get('media_id')}")
                print(f"  Subdocuments: {save_result.get('subdocument_count', 0)}")
                print(f"  Parent KVs: {save_result.get('parent_kv_count', 0)}, Images: {save_result.get('parent_image_count', 0)}")
                print(f"  Subdoc KVs: {save_result.get('subdoc_kv_count', 0)}, Images: {save_result.get('subdoc_image_count', 0)}")
            else:
                print(f"✗ Save failed: {save_result.get('message')}")

        except Exception as e:
            print(f"✗ Error processing {filename}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "filename": filename,
                "error": str(e),
                "success": False,
            })

    successful = sum(1 for r in results if r.get("success"))
    failed = total - successful

    print("\n" + "=" * 60)
    print(f"[Batch Re-ingest] Completed")
    print(f"[Batch Re-ingest] Success: {successful}")
    print(f"[Batch Re-ingest] Failed: {failed}")
    print("=" * 60)

    return {
        "session_id": session_id,
        "total": total,
        "successful": successful,
        "failed": failed,
        "results": results
    }

