import json
from chatbot.models import Media, KeyValue
from chatbot.models.media_models import MediaImage


def export_media_hierarchy(media_id=None, output_file=None, limit=None):
    """
    Export media with parent-child hierarchy to JSON
    """

    if media_id:
        # Export specific media and its children
        try:
            parent_media = Media.objects.get(id=media_id)
            media_queryset = [parent_media]
            # Get all children
            children = Media.objects.filter(parent_id=media_id)
            media_queryset.extend(children)
        except Media.DoesNotExist:
            print(f"Media with ID {media_id} not found")
            return []
    else:
        # Export ALL parent media (default behavior)
        print("Exporting ALL parent media...")
        media_queryset = Media.objects.filter(
            parent__isnull=True  # Only get parent documents
        ).order_by('-created_at')
        if limit:
            media_queryset = media_queryset[:limit]
        total_count = Media.objects.filter(parent__isnull=True).count()
        print(f"Found {total_count} total parent documents")
        if limit:
            print(f"Exporting first {limit} documents")
        else:
            print(f"Exporting all {total_count} documents")

    exported_data = []

    for media in media_queryset:
        # Handle None values for extracted_text
        extracted_text = media.extracted_text or ''

        # Convert tags to strings for JSON serialization
        # Tags is a ManyToManyField to Tag model
        tags = []
        if hasattr(media, 'tags'):
            try:
                # Get all tag names from the ManyToMany relationship
                tags = list(media.tags.values_list('name', flat=True))
            except (TypeError, AttributeError) as e:
                print(f"Error getting tags for media {media.id}: {e}")
                tags = []

        media_dict = {
            'id': media.id,
            'name': str(media.name) if media.name else '',
            'media_type': str(media.media_type) if media.media_type else '',
            'description': str(media.description) if media.description else '',
            'priority': str(media.priority) if media.priority else '',
            'organization': media.organization.slug if media.organization else '',  # Save slug instead of name
            'file_url': media.get_s3_url() if media.file else '',  # Add S3 URL for file download
            'extracted_text': extracted_text,  # Full text, not truncated
            'extracted_text_length': len(extracted_text),
            'tags': tags,
            'parent_id': media.parent_id,
            'company_bot_id': media.company_bot_id,
            'created_at': str(media.created_at),
        }

        # Get key-values
        key_values = KeyValue.objects.filter(media=media)
        media_dict['key_values'] = [
            {'key': str(kv.key), 'value': str(kv.value) if kv.value else ''}
            for kv in key_values
        ]
        media_dict['key_value_count'] = len(media_dict['key_values'])

        # Get images
        images = MediaImage.objects.filter(media=media)
        media_dict['images'] = [
            {'image_url': str(img.image_url) if img.image_url else '',
             'caption': str(img.caption) if img.caption else ''}
            for img in images
        ]
        media_dict['image_count'] = len(media_dict['images'])

        # Get subdocuments (children)
        children = Media.objects.filter(parent=media)
        subdocuments = []

        for child in children:
            # Handle None values for child extracted_text
            child_extracted_text = child.extracted_text or ''

            # Convert child tags to strings for JSON serialization
            child_tags = []
            if hasattr(child, 'tags'):
                try:
                    # Get all tag names from the ManyToMany relationship
                    child_tags = list(child.tags.values_list('name', flat=True))
                except (TypeError, AttributeError) as e:
                    print(f"Error getting tags for child media {child.id}: {e}")
                    child_tags = []

            child_dict = {
                'id': child.id,
                'name': str(child.name) if child.name else '',
                'media_type': str(child.media_type) if child.media_type else '',
                'description': str(child.description) if child.description else '',
                'priority': str(child.priority) if child.priority else '',
                'extracted_text': child_extracted_text[:200] + '...' if len(child_extracted_text) > 200 else child_extracted_text,
                'extracted_text_length': len(child_extracted_text),
                'tags': child_tags,
                'parent_id': child.parent_id,
                'created_at': str(child.created_at),
            }

            # Get child key-values
            child_kvs = KeyValue.objects.filter(media=child)
            child_dict['key_values'] = [
                {'key': str(kv.key), 'value': str(kv.value) if kv.value else ''}
                for kv in child_kvs
            ]
            child_dict['key_value_count'] = len(child_dict['key_values'])

            # Get child images
            child_images = MediaImage.objects.filter(media=child)
            child_dict['images'] = [
                {'image_url': str(img.image_url) if img.image_url else '',
                 'caption': str(img.caption) if img.caption else ''}
                for img in child_images
            ]
            child_dict['image_count'] = len(child_dict['images'])

            subdocuments.append(child_dict)

        media_dict['subdocuments'] = subdocuments
        media_dict['subdocument_count'] = len(subdocuments)

        exported_data.append(media_dict)

    # Print summary
    print("\n" + "=" * 60)
    print("EXPORT SUMMARY")
    print("=" * 60)
    print(f"Total parent documents: {len(exported_data)}")

    total_subdocs = sum(m['subdocument_count'] for m in exported_data)
    total_kvs = sum(m['key_value_count'] for m in exported_data)
    total_subdoc_kvs = sum(
        sum(s['key_value_count'] for s in m['subdocuments'])
        for m in exported_data
    )
    total_images = sum(m['image_count'] for m in exported_data)
    total_subdoc_images = sum(
        sum(s['image_count'] for s in m['subdocuments'])
        for m in exported_data
    )

    print(f"Total subdocuments: {total_subdocs}")
    print(f"Total parent key-values: {total_kvs}")
    print(f"Total subdocument key-values: {total_subdoc_kvs}")
    print(f"Total parent images: {total_images}")
    print(f"Total subdocument images: {total_subdoc_images}")
    print("=" * 60)

    # Print hierarchy tree
    print("\nHIERARCHY TREE:")
    print("-" * 60)
    for media in exported_data:
        print(f"📄 {media['name']} (ID: {media['id']})")
        print(f"   ├─ KVs: {media['key_value_count']}, Images: {media['image_count']}")
        print(f"   ├─ Text length: {media['extracted_text_length']} chars")
        print(f"   └─ Subdocuments: {media['subdocument_count']}")

        for i, subdoc in enumerate(media['subdocuments']):
            is_last = i == len(media['subdocuments']) - 1
            prefix = "      └─" if is_last else "      ├─"
            print(f"{prefix} 📑 {subdoc['name']} (ID: {subdoc['id']}, parent_id: {subdoc['parent_id']})")
            print(f"         ├─ KVs: {subdoc['key_value_count']}, Images: {subdoc['image_count']}")
            print(f"         └─ Text length: {subdoc['extracted_text_length']} chars")

        print()

    # Save to file if specified
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(exported_data, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Exported to: {output_file}")

    return exported_data


def verify_hierarchy(media_id):
    """
    Verify that parent-child relationships are correctly set

    Args:
        media_id: Parent media ID to verify
    """
    try:
        parent = Media.objects.get(id=media_id)
        children = Media.objects.filter(parent_id=media_id)

        print("\n" + "=" * 60)
        print("HIERARCHY VERIFICATION")
        print("=" * 60)
        print(f"Parent Media ID: {parent.id}")
        print(f"Parent Name: {parent.name}")
        print(f"Parent has parent_id: {parent.parent_id}")
        print(f"\nChildren count: {children.count()}")

        for child in children:
            print(f"\n  Child ID: {child.id}")
            print(f"  Child Name: {child.name}")
            print(f"  Child parent_id: {child.parent_id}")
            print(f"  ✓ Correctly linked: {child.parent_id == parent.id}")

        print("=" * 60)

        return {
            'parent_id': parent.id,
            'parent_name': parent.name,
            'children_count': children.count(),
            'all_linked_correctly': all(c.parent_id == parent.id for c in children)
        }

    except Media.DoesNotExist:
        print(f"Media with ID {media_id} not found")
        return None


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

# Example 1: Export ALL media (all parent documents with their children)
# result = export_media_hierarchy(output_file='/tmp/all_media_export.json')
