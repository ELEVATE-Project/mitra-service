from django.db import models
from simple_history.models import HistoricalRecords

from chatbot.models import Profile


class MitraProject(models.Model):

    profile = models.ForeignKey(Profile, on_delete=models.DO_NOTHING, null=True, blank=True)

    session = models.CharField(max_length=400, unique=True)
    project_id = models.CharField(max_length=400, unique=True)
    program_id = models.CharField(max_length=400, null=True, blank=True)

    title = models.CharField(max_length=300, null=True, blank=True)
    problem_statement = models.TextField(null=True, blank=True)
    objective = models.TextField(null=True, blank=True)
    actions = models.TextField(null=True, blank=True)
    duration = models.CharField(max_length=50, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    def __str__(self):
        return self.title

    class Meta:
        indexes = [
            models.Index(fields=['title', 'session', 'project_id', 'program_id', 'created_at', 'profile']),
        ]
