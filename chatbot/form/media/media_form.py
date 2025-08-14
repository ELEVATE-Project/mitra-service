from django import forms
from django.contrib import admin
from chatbot.models.media_models import Media, Tag

BOT_PROFILE_ID = 1


class MediaAdminForm(forms.ModelForm):
    manual_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.exclude(created_by_id=BOT_PROFILE_ID),
        required=False,
        widget=admin.widgets.FilteredSelectMultiple("Manual Tags", is_stacked=False)
    )
    auto_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),  # placeholder
        required=False,
        widget=admin.widgets.FilteredSelectMultiple("Auto Tags", is_stacked=False),
        # disabled=True
    )

    class Meta:
        model = Media
        fields = '__all__'
        exclude = ['tags']  # Exclude the original tags field since we're handling it manually

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Always set manual_tags queryset
        self.fields['manual_tags'].queryset = Tag.objects.exclude(created_by_id=BOT_PROFILE_ID)

        if getattr(self.instance, 'pk', None):
            # Existing instance
            self.fields['manual_tags'].initial = self.instance.tags.exclude(created_by_id=BOT_PROFILE_ID)

            if hasattr(self.instance, '_auto_tags_to_preserve'):
                auto_qs = self.instance._auto_tags_to_preserve
            else:
                auto_qs = self.instance.tags.filter(created_by_id=BOT_PROFILE_ID)

            if auto_qs.exists() if hasattr(auto_qs, 'exists') else auto_qs:
                self.fields['auto_tags'].queryset = auto_qs
                self.fields['auto_tags'].initial = auto_qs
            else:
                self.fields.pop('auto_tags')
        else:
            # New object → hide auto_tags field
            self.fields.pop('auto_tags', None)

    def save(self, commit=True):
        # Save instance first to ensure it has an ID
        instance = super().save(commit=False)
        manual_tags = list(self.cleaned_data.get('manual_tags', []))
        print("manual_tags: ", manual_tags)
        if commit:
            auto_tags = list(instance.tags.filter(created_by_id=BOT_PROFILE_ID))
        else:
            auto_tags = list(self.cleaned_data.get('auto_tags', []))
        print("auto_tags: ", auto_tags)

        if commit:
            print("Commit is True")
            instance.save()  # Now instance.pk exists
            print("Cleaned Data: ", self.cleaned_data)
            # Store manual tags from form
            # manual_tags = list(self.cleaned_data.get('manual_tags', []))

            # For existing instances, preserve auto tags
            if instance.pk:
                # Set all tags (manual + auto)
                instance.tags.set(manual_tags + auto_tags)
            else:
                # For new instances, just set manual tags
                instance.tags.set(manual_tags)
        else:
            print("Commit is False")
            # Even if not committing, attach manual tags to the instance's m2m cache
            instance._manual_tags_to_set = manual_tags
            instance._auto_tags_to_preserve = auto_tags

        print("Instance: ", instance)
        return instance
