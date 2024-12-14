from django.db import models
from django.utils.translation import gettext_lazy as _


class ProjectUserType(models.TextChoices):
    PRINCIPAL = 'PRINCIPAL', _('PRINCIPAL')
    TEACHER = 'TEACHER', _('TEACHER')
    SPD = 'SPD', _('SPD')
    DEO = 'DEO', _('DEO')
    BEO = 'BEO', _('BEO')
    HM = 'HM', _('HM')
    HT = 'HT', _('HT')
    AT = 'AT', _('AT')


class ProjectStatus(models.TextChoices):
    STARTED = 'STARTED', _('STARTED')
    IN_PROGRESS = 'inPROGRESS', _('inPROGRESS')
    SUBMITTED = 'SUBMITTED', _('SUBMITTED')


class TaskMandatoryStatus(models.TextChoices):
    YES = 'YES', _('YES')
    NO = 'NO', _('NO')

class ProjectCreatedBy(models.TextChoices):
    AI_GENERATED = 'AI_GENERATED', _('AI_GENERATED')
    EXPERT_VETTED = 'EXPERT_VETTED', _('EXPERT_VETTED')

