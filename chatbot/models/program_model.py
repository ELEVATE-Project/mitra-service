from django.contrib.auth.models import User
from django.db import models
from simple_history.models import HistoricalRecords


class Program(models.Model):
    """
    Master list of programmes a report can belong to, such as Shiksha Chaupal.
    Programmes are supplied by the product team before a programme goes live on Mitra, and
    a report is tagged with one through the bot and state it came from.
    """

    program_uuid = models.CharField(max_length=500, unique=True)
    name = models.CharField(max_length=1000, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name or self.program_uuid

    class Meta:
        indexes = [
            models.Index(fields=['program_uuid']),
            models.Index(fields=['name']),
            models.Index(fields=['created_at']),
        ]
