from django.db import models
from chatbot.models import CompanyBot, EntityTypeChoices, PreProcessType, PreProcessOutputMode, PostProcessType, \
    PostProcessOutputMode
from simple_history.models import HistoricalRecords
from django.core.exceptions import ValidationError


class CompanyStateMachine(models.Model):
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, help_text="Enter the name of the state.")
    step = models.IntegerField(
        help_text="Integer representing the order in which state function calling happens. Lower values are "
                  "called first."
    )
    use_stage_chats = models.BooleanField(
        default=False,
        verbose_name="Use Stage Chats",
        help_text="If True, only chats from this stage will be included and passed to the LLM."
    )
    type = models.CharField(
        max_length=10, choices=EntityTypeChoices.choices, default=EntityTypeChoices.MANDATORY,
        help_text="Specify whether the state is mandatory or optional."
    )
    bot_question = models.TextField(
        null=True, blank=True, help_text="Provide the first question that the bot will ask when the state is triggered."
    )
    completion_criteria = models.TextField(
        null=True, blank=True,
        help_text="Define the criteria required to move from this state to the next state."
    )
    context = models.TextField(
        null=True, blank=True, help_text="Provide the main prompt or description of the state, explaining its purpose."
    )
    preprocess_type = models.CharField(
        max_length=10, choices=PreProcessType.choices, default=PreProcessType.NONE,
        help_text="Choose how this stage should be preprocessed: "
        "'Simple Prompt' lets you define a direct prompt, "
        "'Use Preprocess Bot' lets you select a separate bot to handle complex logic."
    )

    preprocess_prompt = models.TextField(
        blank=True, null=True,
        help_text="Define the skip logic prompt if Preprocess Type is SIMPLE. "
    )

    preprocess_bot = models.ForeignKey(
        CompanyBot,
        on_delete=models.SET_NULL, null=True, blank=True, related_name='preprocess_bots',
        help_text="Select which Bot to use for preprocessing for complex logic."
    )

    preprocess_output_mode = models.CharField(
        max_length=10, choices=PreProcessOutputMode.choices, default=PreProcessOutputMode.NONE,
        help_text="Define how to use the preprocess output: "
        "'Skip' means use output to decide if stage should be skipped; "
        "'Enrich' means use output in this stage's prompt; "
        "'Custom' means run custom logic on the output."
    )
    postprocess_type = models.CharField(
        max_length=10, choices=PostProcessType.choices, default=PostProcessType.NONE,
        help_text="Choose how this stage should be postprocessed: "
                  "'Simple Prompt' lets you define a direct prompt, "
                  "'Use Postprocess Bot' lets you select a separate bot to handle complex logic."
    )

    postprocess_prompt = models.TextField(
        blank=True, null=True,
        help_text="Define the postprocess prompt if Postprocess Type is SIMPLE."
    )

    postprocess_bot = models.ForeignKey(
        CompanyBot,
        on_delete=models.SET_NULL, null=True, blank=True, related_name='postprocess_bots',
        help_text="Select which Bot to use for postprocessing for complex logic."
    )

    postprocess_output_mode = models.CharField(
        max_length=10, choices=PostProcessOutputMode.choices, default=PostProcessOutputMode.NONE,
        help_text="Define how to use the postprocess output."
    )

    skip_to_step = models.IntegerField(
        null=True, blank=True,
        help_text="If set, the flow will skip directly to this step number when skip conditions are met."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def clean(self):
        # --- Preprocess validation ---
        if self.preprocess_type == PreProcessType.SIMPLE:
            if not self.preprocess_prompt or self.preprocess_prompt.strip() == '':
                raise ValidationError({
                    'preprocess_prompt': "Preprocess prompt is required when Preprocess Type is SIMPLE."
                })
            if self.preprocess_output_mode == PreProcessOutputMode.NONE:
                raise ValidationError({
                    'output_mode': "Output mode cannot be NONE when Preprocess Type is SIMPLE."
                })

        elif self.preprocess_type == PreProcessType.COMPLEX:
            if not self.preprocess_bot:
                raise ValidationError({
                    'preprocess_bot': "Preprocess bot must be selected for the selected preprocess type."
                })
            if self.preprocess_output_mode == PreProcessOutputMode.NONE:
                raise ValidationError({
                    'output_mode': "Output mode cannot be NONE for the selected preprocess type."
                })
        else:
            self.preprocess_prompt = None
            self.preprocess_bot = None
            self.preprocess_output_mode = PreProcessOutputMode.NONE

        # --- Postprocess validation ---
        if self.postprocess_type == PostProcessType.SIMPLE:
            if not self.postprocess_prompt or self.postprocess_prompt.strip() == '':
                raise ValidationError({
                    'postprocess_prompt': "Postprocess prompt is required when Postprocess Type is SIMPLE."
                })
            if self.postprocess_output_mode == PostProcessOutputMode.NONE:
                raise ValidationError({
                    'postprocess_output_mode': "Output mode cannot be NONE when Postprocess Type is SIMPLE."
                })
        elif self.postprocess_type == PostProcessType.COMPLEX:
            if not self.postprocess_bot:
                raise ValidationError({
                    'postprocess_bot': "Postprocess bot must be selected for the selected postprocess type."
                })
            if self.postprocess_output_mode == PostProcessOutputMode.NONE:
                raise ValidationError({
                    'postprocess_output_mode': "Output mode cannot be NONE for the selected postprocess type."
                })
        else:
            self.postprocess_prompt = None
            self.postprocess_bot = None
            self.postprocess_output_mode = PostProcessOutputMode.NONE

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)