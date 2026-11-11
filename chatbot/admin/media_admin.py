from django.contrib import admin
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.contrib.admin.decorators import action
from .generic_upload_admin import BatchUploadMixin
from chatbot.filter.custom_date_from_filter import CustomAdvanceDateFilter
from chatbot.form.media.media_form import MediaAdminForm
from chatbot.models import Tag, Profile, TagChoices, TagSourceChoices
from chatbot.models.media_models import Media, KeyValue, MediaImage
from chatbot.models.enums import FileDisplayMode, ProfileType
from simple_history.admin import SimpleHistoryAdmin
from chatbot.utils.knowledge_service.cache_manager import GetCachedItemView
from chatbot.views.Media.extract_views import BatchMediaExtractView, BatchMediaRetryExtractView
from chatbot.views.Media.save_views import BatchMediaSaveView, BatchMediaRetrySaveView
from chatbot.views.Media.status_views import BatchMediaTaskStatusView, VectorDBTaskStatusView
from chatbot.views.Media.upload_views import BatchMediaUploadView


class KeyValueInline(admin.TabularInline):
    """Inline editor for the key-value pairs attached to a Media object."""

    model = KeyValue
    extra = 1


class MediaImagesInline(admin.TabularInline):
    """Inline editor for the images extracted from a Media object."""

    model = MediaImage
    extra = 1
    fk_name = 'media'
    fields = ('name', 'media_type', 'page', 'width', 'height')
    readonly_fields = ('created_at',)


@admin.register(Media)
class MediaAdmin(SimpleHistoryAdmin, admin.ModelAdmin):
    """Admin for Media files, with tag handling, display-mode bulk change and batch upload URLs."""

    form = MediaAdminForm
    list_display = (
        'file_name', 'get_title', 'media_type', 'display_mode', 'parent__name',
        'view_count', 'download_count', 'updated_at', 'created_at'
    )
    list_filter = (
        CustomAdvanceDateFilter,
        'display_mode',
        'name',
        'media_type',
        'company_bot'
    )
    search_fields = ('name', 'key_values__value')
    actions = ['export_selected', 'change_display_mode_action']
    list_export = ('csv', 'xlsx')
    inlines = [KeyValueInline, MediaImagesInline]
    raw_id_fields = ('company_bot', 'parent', 'organization')
    date_hierarchy = 'created_at'
    readonly_fields = ('view_count', 'download_count', 'thumbnail')
    ordering = ('-created_at',)

    def file_name(self, obj):
        """Return the Media name for the list display.

        Args:
            obj (Media): The Media row being listed.

        Returns:
            str: The value of ``obj.name``.
        """
        return obj.name

    file_name.short_description = "File name"

    def get_title(self, obj):
        """Return the TITLE key-value for the list display, truncated to 50 characters.

        Args:
            obj (Media): The Media row being listed.

        Returns:
            str: The title, shortened with "..." if longer than 50 characters.
                "-" if there is no title or the lookup fails.
        """
        try:
            title_kv = obj.key_values.filter(key__iexact='title').first()
            if title_kv and title_kv.value:
                # Truncate long titles for display
                title = title_kv.value
                if len(title) > 50:
                    return f"{title[:47]}..."
                return title
            return "-"
        except Exception:
            return "-"

    get_title.short_description = 'Title'
    get_title.admin_order_field = 'key_values__value'

    def get_queryset(self, request):
        """Return the changelist queryset with related objects prefetched.

        Prefetching key values, tags and parent avoids one query per row in the list view.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            QuerySet: The Media queryset with prefetches applied.
        """
        qs = super().get_queryset(request)
        return qs.prefetch_related('key_values', 'tags', 'parent')

    def save_model(self, request, obj, form, change):
        """Save the Media object, then set its tags from the manual and preserved auto tags.

        Manual tags come from ``obj._manual_tags_to_set`` and auto tags from
        ``obj._auto_tags_to_preserve``. Both are set by the form. Missing attributes
        are treated as empty lists.

        Args:
            request (HttpRequest): The current admin request.
            obj (Media): The Media instance being saved.
            form (ModelForm): The bound admin form.
            change (bool): True when editing an existing object, False when creating one.
        """
        super().save_model(request, obj, form, change)

        manual_tags = getattr(obj, '_manual_tags_to_set', [])
        auto_tags = getattr(obj, '_auto_tags_to_preserve', [])

        print("manual_tags to set:", manual_tags)
        print("auto_tags to preserve:", auto_tags)

        obj.tags.set(manual_tags + auto_tags)

    def get_fieldsets(self, request, obj=None):
        """Build the form layout, with fewer editable fields for moderators.

        Moderators cannot edit ``company_bot``, ``parent`` or ``priority``. The
        "Auto Tags" fieldset appears only for saved objects that have tags created by
        user 1 (the automatic tagger).

        Args:
            request (HttpRequest): The current admin request. Used to find the user's Profile.
            obj (Media | None): The Media being edited, or None when adding a new one.

        Returns:
            list[tuple]: Django fieldset definitions for the change form.
        """
        # Check if user is a MODERATOR
        is_moderator = False
        try:
            profile = Profile.objects.get(email=request.user.email)
            is_moderator = profile.profile_type == ProfileType.MODERATOR
            print("Is User Moderator: ", is_moderator)
        except Profile.DoesNotExist:
            is_moderator = False

        if is_moderator:
            base_fields = ('name', 'organization', 'file', 'markdown_file', 'thumbnail', 'url', 'display_mode', 'description', 'extracted_text',
                           'media_type', 'view_count', 'download_count')
        else:
            base_fields = (
                'name', 'organization', 'file', 'markdown_file', 'thumbnail', 'url', 'display_mode', 'description', 'extracted_text', 'priority',
                'media_type', 'company_bot', 'parent', 'view_count', 'download_count'
            )

        fieldsets = [
            (None, {
                'fields': base_fields
            }),
            ('Manual Tags', {
                'fields': ('manual_tags',),
            }),
        ]

        if obj and obj.pk:
            if obj.tags.filter(created_by_id=1).exists():
                fieldsets.append(
                    ('Auto Tags', {
                        'fields': ('auto_tags',),
                        'description': 'Automatically generated tags'
                    })
                )

        return fieldsets

    def get_actions(self, request):
        """Return the admin actions for the changelist.

        Currently this returns Django's default action set unchanged. The
        "delete selected" action is kept, and the code to remove it is commented out.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            dict: Map of action name to (function, name, description).
        """
        actions = super().get_actions(request)
        # if 'delete_selected' in actions:
        #     del actions['delete_selected']
        return actions

    @action(description="Change display mode")
    def change_display_mode_action(self, request, queryset):
        """Store the selected Media IDs in the session and redirect to the display-mode form.

        Args:
            request (HttpRequest): The current admin request. The session stores the IDs.
            queryset (QuerySet): The Media objects selected in the changelist.

        Returns:
            HttpResponseRedirect: Redirect to the ``change-display-mode/`` view.
        """
        # Store the selected objects in the session for processing
        selected_ids = queryset.values_list('id', flat=True)
        request.session['selected_media_ids'] = list(selected_ids)

        # Redirect to the display mode change view
        return HttpResponseRedirect(f"{request.path}change-display-mode/")

    def change_display_mode(self, request):
        """Show the display-mode form (GET) or apply the chosen mode (POST).

        The selected IDs come from the session, set by ``change_display_mode_action``.
        POST accepts ``display_mode`` and ``apply_to``. ``apply_to='all'`` updates every
        Media row. Any other value updates only the selected rows.

        Args:
            request (HttpRequest): The current admin request.

        Returns:
            HttpResponse: The form page on GET, or a redirect after a POST or error.
        """
        selected_ids = request.session.get('selected_media_ids', [])

        if not selected_ids:
            self.message_user(request, "No files selected.", level="error")
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', '../'))

        if request.method == 'POST':
            new_display_mode = request.POST.get('display_mode')
            apply_to = request.POST.get('apply_to', 'selected')

            if not new_display_mode:
                self.message_user(request, "Please select a display mode.", level="error")
                return HttpResponseRedirect(request.path)

            # Determine which objects to update
            if apply_to == 'all':
                media_objects = Media.objects.all()
            else:
                media_objects = Media.objects.filter(id__in=selected_ids)

            # Update display_mode for selected/all objects
            updated_count = media_objects.update(display_mode=new_display_mode)

            self.message_user(
                request,
                f"Successfully updated display mode for {updated_count} file(s) to '{new_display_mode}'."
            )

            # Clear the session
            if 'selected_media_ids' in request.session:
                del request.session['selected_media_ids']

            return HttpResponseRedirect('../')

        # GET request - show the form
        context = {
            'title': 'Change Display Mode',
            'selected_count': len(selected_ids),
            'display_mode_choices': FileDisplayMode.choices,
        }
        return render(request, 'admin/change_display_mode.html', context)

    def get_urls(self):
        """Add the custom admin URLs for display mode, batch upload and the API endpoints.

        Custom routes are placed before Django's default routes so they match first.

        Returns:
            list[django.urls.URLPattern]: The custom URL patterns followed by the default ones.
        """
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                'change-display-mode/',
                self.admin_site.admin_view(self.change_display_mode),
                name='chatbot_media_change_display_mode'
            ),
            path('batch-upload/',
                 self.admin_site.admin_view(BatchMediaUploadView.as_view()),
                 name='chatbot_media_batch_upload'),
            path('api/batch-extract/',
                 self.admin_site.admin_view(BatchMediaExtractView.as_view()),
                 name='chatbot_media_batch_extract'),
            path('api/batch-save/',
                 self.admin_site.admin_view(BatchMediaSaveView.as_view()),
                 name='chatbot_media_batch_save'),
            path('api/batch-task-status/',
                 self.admin_site.admin_view(BatchMediaTaskStatusView.as_view()),
                 name='chatbot_media_task_status'),
            path('api/retry-extract/',
                 self.admin_site.admin_view(BatchMediaRetryExtractView.as_view()),
                 name='chatbot_media_retry_extract'),
            path('api/retry-save/',
                 self.admin_site.admin_view(BatchMediaRetrySaveView.as_view()),
                 name='chatbot_media_retry_save'),
            path('api/vector-db-task-status/',
                 self.admin_site.admin_view(VectorDBTaskStatusView.as_view()),
                 name='chatbot_media_vector_db_task_status'),
            path('api/get-cached-item/',
                 self.admin_site.admin_view(GetCachedItemView.as_view()),
                 name='chatbot_media_get_cached_item'),
        ]
        return custom_urls + urls

    def delete_queryset(self, request, queryset):
        """Delete the selected Media objects one at a time, collecting any failures.

        Deleting per object means one failure does not stop the others. Failed IDs
        and their error messages are shown to the user as an error message.

        Args:
            request (HttpRequest): The current admin request, used for the message.
            queryset (QuerySet): The Media objects to delete.
        """
        errors = []

        for obj in queryset:
            try:
                obj.delete()
            except Exception as e:
                errors.append(f"{obj.id}: {str(e)}")

        if errors:
            self.message_user(
                request,
                f"Some files failed to delete:\n" + "\n".join(errors),
                level="error"
            )


@admin.register(Tag)
class MasterTagAdmin(BatchUploadMixin, admin.ModelAdmin):
    """Admin for master tags, with batch upload support."""

    list_display = ('name', 'status', 'source_type', 'created_by', 'created_at')
    list_filter = (
        CustomAdvanceDateFilter,
        'name',
        'created_by',
        'source_type'
    )
    raw_id_fields = ('created_by',)
    readonly_fields = ('source_type', 'company', 'created_by')
    search_fields = ('name', 'description')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    enable_batch_upload = True
    batch_upload_fields = ['name', 'status', 'description', 'created_by']

    def save_model(self, request, obj, form, change):
        """Save a new tag as APPROVED and MANUAL, linked to the requesting user's Profile.

        Existing tags are saved without changes to these fields.

        Args:
            request (HttpRequest): The current admin request. Used to find the user's Profile.
            obj (Tag): The Tag instance being saved.
            form (ModelForm): The bound admin form.
            change (bool): True when editing an existing object, False when creating one.
        """
        print("In save")
        if not obj.pk:
            print("obj.pk= ", obj.pk)
            try:
                print("request.user.email: ", request.user.email)
                profile = Profile.objects.get(email=request.user.email)
                print("profile found: ", profile)
            except Profile.DoesNotExist:
                print("Exception profile doesnot exist")
                profile = None
            obj.created_by = profile
            obj.status = TagChoices.APPROVED
            obj.source_type = TagSourceChoices.MANUAL
        super().save_model(request, obj, form, change)