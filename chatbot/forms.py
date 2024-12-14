from django import forms

from chatbot.models.media_models import Media


class MediaAdminForm(forms.ModelForm):
    class Meta:
        model = Media
        exclude = ('vector_id',)
