# from import_export import resources
# from chatbot.models import Story, MediaTypeChoices
# from datetime import datetime
#
#
# class StoryResource(resources.ModelResource):
#     class Meta:
#         model = Story
#         fields = (
#             'id', 'title', 'author', 'session', 'created_at',
#             'pdf_url'
#         )
#
#     def export_resource(self, obj, *, export_fields=None, **kwargs):
#         data = super().export_resource(obj, export_fields=export_fields, **kwargs)
#         print("data: ", data)
#         if export_fields is None:
#             print("Export fields is none")
#             export_fields = self.get_export_fields()
#
#         print("export fields: ", export_fields)
#         # Loop through fields and data together
#         for i, (field, value) in enumerate(zip(export_fields, data)):
#             if isinstance(value, datetime) and value.tzinfo is not None:
#                 data[i] = value.replace(tzinfo=None)
#
#         return data
#
#     def dehydrate_pdf_url(self, obj):
#         """
#         Returns the public URL of the first associated PDF media, if any.
#         """
#         pdf_media = obj.story_media.filter(media_type=MediaTypeChoices.PDF).first()
#         if pdf_media:
#             return pdf_media.get_public_url()
#         return ""


from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from chatbot.models import Story, Profile

class StoryResource(resources.ModelResource):
    title = fields.Field(attribute='title', column_name='Title')
    author = fields.Field(attribute='author', column_name='Author', widget=ForeignKeyWidget(Profile, 'id'))
    content = fields.Field(attribute='content', column_name='Content')
    blurb = fields.Field(attribute='blurb', column_name='Blurb')
    session = fields.Field(attribute='session', column_name='Session')
    objective = fields.Field(attribute='objective', column_name='Objective')
    action_steps = fields.Field(attribute='action_steps', column_name='Action Steps')
    impact = fields.Field(attribute='impact', column_name='Impact')
    micro_improvement = fields.Field(attribute='micro_improvement', column_name='Micro Improvement')
    location = fields.Field(attribute='location', column_name='Location')
    formatted_content = fields.Field(attribute='formatted_content', column_name='Formatted Content')
    language = fields.Field(attribute='language', column_name='Language')
    source = fields.Field(attribute='source', column_name='Source')
    summary = fields.Field(attribute='summary', column_name='Summary')
    other_params = fields.Field(attribute='other_params', column_name='Other Params')
    created_at = fields.Field(attribute='created_at', column_name='Created At')

    class Meta:
        model = Story
        fields = (
            'title', 'author', 'content', 'blurb', 'session', 'objective', 'action_steps',
            'impact', 'micro_improvement', 'location', 'formatted_content', 'language',
            'source', 'summary', 'other_params', 'created_at'
        )
