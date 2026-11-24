import json
from django.test import TestCase, RequestFactory
from django.core.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from chatbot.models import Company, Profile, ProfileType, ChatSession, ChatStatus
from chatbot.models.company_models import CompanyBot, CompanyStateMachine
from chatbot.models.enums import OperationTypeChoices, ValidateMethodChoices, ValidationTypeChoices, RenderAsChoices
from chatbot.admin.forms import ChoicesWidget, ErrorMessagesWidget, CompanyStateMachineForm
from chatbot.serializer.company_serializer import CompanyBotSerializer
from chatbot.utils.chat_utils import build_validation_response
from chatbot.views.chat_view import create_chatsession, non_llm_chat_view
from chatbot.views.drf_views import BotVernacularListCreateView


class ConfigurableValidationsTest(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="ShikshaLokam", slug="shikshalokamstaging")
        self.ai_profile = Profile.objects.create(
            id=1,
            first_name="AI", last_name="Assistant", email="ai@example.com",
            profile_type=ProfileType.USER, company=self.company
        )
        self.profile = Profile.objects.create(
            id=2,
            userid="test-user-id",
            first_name="Test", last_name="User", email="test@example.com",
            profile_type=ProfileType.USER, company=self.company
        )
        self.bot = CompanyBot.objects.create(
            name="Test Bot", company=self.company, route="/test-bot", context="Test context"
        )

        # Step 1: Multiple choice
        self.sm1 = CompanyStateMachine.objects.create(
            company_bot=self.bot,
            name="Step 1 Question",
            step=1,
            operation_type=OperationTypeChoices.NON_LLM,
            bot_question="Select role",
            validate_method=ValidateMethodChoices.FE,
            validation_type=ValidationTypeChoices.MULTIPLE_CHOICE,
            render_as=RenderAsChoices.BUTTONS,
            validation_config={"choices": [{"key": "teacher", "label": "Teacher"}, {"key": "student", "label": "Student"}]},
            error_message=[{"key": "required", "labels": {"en": {"text": "Please select a role"}}}],
            min_choices=1,
            max_choices=1,
        )

        # Step 2: Multiple choice
        self.sm2 = CompanyStateMachine.objects.create(
            company_bot=self.bot,
            name="Step 2 Question",
            step=2,
            operation_type=OperationTypeChoices.NON_LLM,
            bot_question="Select grade",
            validate_method=ValidateMethodChoices.FE,
            validation_type=ValidationTypeChoices.MULTIPLE_CHOICE,
            render_as=RenderAsChoices.BUTTONS,
            validation_config={"choices": [{"key": "grade_1", "label": "Grade 1"}, {"key": "grade_2", "label": "Grade 2"}]},
            error_message=[{"key": "required", "labels": {"en": {"text": "Please select a grade"}}}],
            min_choices=1,
            max_choices=2,
        )

    def test_choices_widget_dynamic_prefix_parsing(self):
        """Test ChoicesWidget parses submitted choices for both row 0 and dynamic row 1."""
        widget = ChoicesWidget()

        # Row 0
        data_row0 = {
            "companystatemachine_set-0-choice_label_0": "Teacher",
            "companystatemachine_set-0-choice_label_1": "Student",
        }
        res0 = widget.value_from_datadict(data_row0, {}, "companystatemachine_set-0-choices_field")
        self.assertEqual(len(res0), 2)
        self.assertEqual(res0[0]["label"], "Teacher")
        self.assertEqual(res0[0]["key"], "teacher")

        # Dynamically added Row 1 (via inline clone)
        data_row1 = {
            "companystatemachine_set-1-choice_label_0": "Grade 1",
            "companystatemachine_set-1-choice_label_1": "Grade 2",
        }
        res1 = widget.value_from_datadict(data_row1, {}, "companystatemachine_set-1-choices_field")
        self.assertEqual(len(res1), 2)
        self.assertEqual(res1[0]["label"], "Grade 1")
        self.assertEqual(res1[0]["key"], "grade_1")

    def test_error_messages_widget_dynamic_prefix_parsing(self):
        """Test ErrorMessagesWidget parses errors for both row 0 and dynamic row 1."""
        widget = ErrorMessagesWidget()
        data_row1 = {
            "companystatemachine_set-1-error_key_0": "required",
            "companystatemachine_set-1-error_label_0": "Grade is required",
        }
        res1 = widget.value_from_datadict(data_row1, {}, "companystatemachine_set-1-errors_field")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["key"], "required")
        self.assertEqual(res1[0]["label"], "Grade is required")

    def test_company_state_machine_form_save(self):
        """Test CompanyStateMachineForm builds validation_config and error_message correctly."""
        from chatbot.models.enums import TextConversionType, PreProcessType, PreProcessOutputMode, PostProcessType, PostProcessOutputMode
        prefix = "companystatemachine_set-2"
        form_data = {
            f"{prefix}-company_bot": self.bot.id,
            f"{prefix}-name": "Step 3 Question",
            f"{prefix}-step": 3,
            f"{prefix}-text_conversion_type": TextConversionType.TRANSLATE,
            f"{prefix}-preprocess_type": PreProcessType.NONE,
            f"{prefix}-preprocess_output_mode": PreProcessOutputMode.NONE,
            f"{prefix}-postprocess_type": PostProcessType.NONE,
            f"{prefix}-postprocess_output_mode": PostProcessOutputMode.NONE,
            f"{prefix}-operation_type": OperationTypeChoices.NON_LLM,
            f"{prefix}-validate_method": ValidateMethodChoices.FE,
            f"{prefix}-validation_type": ValidationTypeChoices.MULTIPLE_CHOICE,
            f"{prefix}-render_as": RenderAsChoices.BUTTONS,
            f"{prefix}-min_choices": 1,
            f"{prefix}-max_choices": 1,
            f"{prefix}-choice_label_0": "Maths",
            f"{prefix}-choice_label_1": "Science",
            f"{prefix}-error_key_0": "required",
            f"{prefix}-error_label_0": "Subject is required",
        }
        form = CompanyStateMachineForm(
            data=form_data,
            prefix=prefix
        )
        self.assertTrue(form.is_valid(), form.errors)
        instance = form.save()

        self.assertIsNotNone(instance.validation_config)
        self.assertEqual(len(instance.validation_config["choices"]), 2)
        self.assertEqual(instance.validation_config["choices"][0]["key"], "maths")
        self.assertIsNotNone(instance.error_message)
        self.assertEqual(instance.error_message[0]["key"], "required")

    def test_company_bot_serializer_includes_validations_for_all_steps(self):
        """Test CompanyBotSerializer returns validations for every state machine step."""
        serializer = CompanyBotSerializer(self.bot)
        data = serializer.data
        steps = data.get("state_machine_steps", [])
        self.assertEqual(len(steps), 2)

        # Step 1 validations
        self.assertEqual(steps[0]["step"], 1)
        self.assertIsNotNone(steps[0]["validations"])
        self.assertEqual(steps[0]["validations"]["type"], "MULTIPLE_CHOICE")
        self.assertEqual(len(steps[0]["validations"]["config"]["choices"]), 2)

        # Step 2 validations
        self.assertEqual(steps[1]["step"], 2)
        self.assertIsNotNone(steps[1]["validations"])
        self.assertEqual(steps[1]["validations"]["type"], "MULTIPLE_CHOICE")
        self.assertEqual(len(steps[1]["validations"]["config"]["choices"]), 2)

    def test_create_chatsession_defaults_step_1_and_returns_validations(self):
        """Test create_chatsession initializes current_step=1 and returns Step 1 validations."""
        from unittest.mock import patch
        import jwt

        secret_key = "test-jwt-secret-key"
        token = jwt.encode(
            {"data": {"id": self.profile.userid, "name": "Test User"}, "roles": []},
            secret_key,
            algorithm="HS256"
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/create-chatsession/",
            {
                "session": "test-session-123",
                "bot_route": "/test-bot",
                "email": self.profile.email,
                "preferred_language": {"value": "en"},
            },
            HTTP_X_AUTH_TOKEN=token,
            format="json"
        )

        with patch("chatbot.views.chat_view.JWT_PUBLIC_KEY", secret_key):
            response = create_chatsession(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_step"], 1)
        self.assertEqual(response.data["step"], 1)
        self.assertIsNotNone(response.data["validations"])
        self.assertEqual(response.data["validations"]["type"], "MULTIPLE_CHOICE")
        self.assertEqual(len(response.data["validations"]["config"]["choices"]), 2)

        # Verify chat_session in DB has current_step=1
        session = ChatSession.objects.get(session="test-session-123")
        self.assertEqual(session.current_step, 1)

    def test_non_llm_chat_view_advances_and_returns_step2_validations(self):
        """Test answering Step 1 advances to Step 2 and returns Step 2's validations."""
        session = ChatSession.objects.create(
            session="test-chat-session",
            profile=self.profile,
            company_bot=self.bot,
            current_step=1,
            session_status=ChatStatus.IN_PROGRESS,
        )

        factory = APIRequestFactory()
        request = factory.post("/api/non-llm-chat/", {
            "session": "test-chat-session",
            "profile_id": self.profile.id,
            "message": "Teacher",
            "language": "en",
        }, format="json")

        response = non_llm_chat_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["step"], 2)
        self.assertEqual(response.data["bot_message"], "Select grade")
        self.assertIsNotNone(response.data["validations"])
        self.assertEqual(response.data["validations"]["type"], "MULTIPLE_CHOICE")
        self.assertEqual(response.data["validations"]["config"]["choices"][0]["text"], "Grade 1")

        session.refresh_from_db()
        self.assertEqual(session.current_step, 2)
        # Because Step 2 is the last step, is_complete is True
        self.assertTrue(response.data["is_complete"])
        self.assertEqual(session.session_status, ChatStatus.COMPLETED)

    def test_bot_vernacular_view_returns_step1_and_all_steps(self):
        """Test BotVernacularListCreateView returns first_bot_question and state_machine_steps."""
        from chatbot.models import BotVernacular
        BotVernacular.objects.create(
            company_bot=self.bot, language="en", name="Test Bot English"
        )

        factory = APIRequestFactory()
        request = factory.get(f"/api/bot_vernacular/?language=en&company_bot__route={self.bot.route}")
        view = BotVernacularListCreateView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_bot_question"], "Select role")
        self.assertIsNotNone(response.data["validations"])
        self.assertEqual(len(response.data["validations"]["config"]["choices"]), 2)

        # Full state_machine_steps list includes validations for both steps
        self.assertIn("state_machine_steps", response.data)
        self.assertEqual(len(response.data["state_machine_steps"]), 2)
        self.assertEqual(response.data["state_machine_steps"][1]["step"], 2)
        self.assertIsNotNone(response.data["state_machine_steps"][1]["validations"])

    def test_create_chatsession_initializes_from_lowest_step_0(self):
        """Test create_chatsession initializes unset session with lowest step (0) and preserves resumed step."""
        from unittest.mock import patch
        import jwt

        bot0 = CompanyBot.objects.create(
            name="Step 0 Bot", company=self.company, route="/bot-step-0", context="Step 0 context"
        )
        CompanyStateMachine.objects.create(
            company_bot=bot0,
            name="Step 0 Intro",
            step=0,
            operation_type=OperationTypeChoices.NON_LLM,
            bot_question="Welcome, what is your language?",
            validate_method=ValidateMethodChoices.NONE,
        )
        CompanyStateMachine.objects.create(
            company_bot=bot0,
            name="Step 1 Name",
            step=1,
            operation_type=OperationTypeChoices.NON_LLM,
            bot_question="What is your name?",
            validate_method=ValidateMethodChoices.NONE,
        )

        secret_key = "test-jwt-secret-key"
        token = jwt.encode(
            {"data": {"id": self.profile.userid, "name": "Test User"}, "roles": []},
            secret_key,
            algorithm="HS256",
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/create-chatsession/",
            {
                "session": "test-session-step0",
                "bot_route": "/bot-step-0",
                "email": self.profile.email,
                "preferred_language": {"value": "en"},
            },
            HTTP_X_AUTH_TOKEN=token,
            format="json",
        )

        with patch("chatbot.views.chat_view.JWT_PUBLIC_KEY", secret_key):
            response = create_chatsession(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_step"], 0)
        self.assertEqual(response.data["step"], 0)
        self.assertEqual(response.data["first_bot_question"], "Welcome, what is your language?")

        # Resumed session preserves current_step
        session0 = ChatSession.objects.get(session="test-session-step0")
        session0.current_step = 1
        session0.save(update_fields=["current_step"])

        request_resumed = factory.post(
            "/api/create-chatsession/",
            {
                "session": "test-session-step0",
                "bot_route": "/bot-step-0",
                "email": self.profile.email,
                "preferred_language": {"value": "en"},
            },
            HTTP_X_AUTH_TOKEN=token,
            format="json",
        )

        with patch("chatbot.views.chat_view.JWT_PUBLIC_KEY", secret_key):
            response_resumed = create_chatsession(request_resumed)

        self.assertEqual(response_resumed.status_code, 200)
        self.assertEqual(response_resumed.data["current_step"], 1)
        self.assertEqual(response_resumed.data["step"], 1)
        self.assertEqual(response_resumed.data["first_bot_question"], "What is your name?")

    def test_company_state_machine_inline_formset_rejects_duplicate_steps(self):
        """Test CompanyStateMachineInlineFormSet rejects duplicate steps for the same bot."""
        from django.forms.models import inlineformset_factory
        from chatbot.admin.company_admin import CompanyStateMachineInlineFormSet
        from chatbot.models.enums import TextConversionType, PreProcessType, PreProcessOutputMode, PostProcessType, PostProcessOutputMode

        test_bot = CompanyBot.objects.create(
            name="Inline Formset Bot", company=self.company, route="/inline-formset-bot", context="Context"
        )

        StateMachineFormSet = inlineformset_factory(
            CompanyBot,
            CompanyStateMachine,
            form=CompanyStateMachineForm,
            formset=CompanyStateMachineInlineFormSet,
            fk_name="company_bot",
            extra=2,
        )

        duplicate_data = {
            "companystatemachine_set-TOTAL_FORMS": "2",
            "companystatemachine_set-INITIAL_FORMS": "0",
            "companystatemachine_set-MIN_NUM_FORMS": "0",
            "companystatemachine_set-MAX_NUM_FORMS": "1000",
            "companystatemachine_set-0-step": "1",
            "companystatemachine_set-0-name": "Step 1 A",
            "companystatemachine_set-0-operation_type": OperationTypeChoices.NON_LLM,
            "companystatemachine_set-0-text_conversion_type": TextConversionType.TRANSLATE,
            "companystatemachine_set-0-preprocess_type": PreProcessType.NONE,
            "companystatemachine_set-0-preprocess_output_mode": PreProcessOutputMode.NONE,
            "companystatemachine_set-0-postprocess_type": PostProcessType.NONE,
            "companystatemachine_set-0-postprocess_output_mode": PostProcessOutputMode.NONE,
            "companystatemachine_set-0-validate_method": ValidateMethodChoices.NONE,
            "companystatemachine_set-1-step": "1",
            "companystatemachine_set-1-name": "Step 1 B",
            "companystatemachine_set-1-operation_type": OperationTypeChoices.NON_LLM,
            "companystatemachine_set-1-text_conversion_type": TextConversionType.TRANSLATE,
            "companystatemachine_set-1-preprocess_type": PreProcessType.NONE,
            "companystatemachine_set-1-preprocess_output_mode": PreProcessOutputMode.NONE,
            "companystatemachine_set-1-postprocess_type": PostProcessType.NONE,
            "companystatemachine_set-1-postprocess_output_mode": PostProcessOutputMode.NONE,
            "companystatemachine_set-1-validate_method": ValidateMethodChoices.NONE,
        }

        formset = StateMachineFormSet(data=duplicate_data, instance=test_bot)
        self.assertFalse(formset.is_valid())
        self.assertTrue(
            any("Duplicate step 1. Each step must be unique for a bot." in str(err) for err in formset.non_form_errors())
        )

        # Distinct steps pass
        valid_data = dict(duplicate_data)
        valid_data["companystatemachine_set-1-step"] = "2"
        valid_formset = StateMachineFormSet(data=valid_data, instance=test_bot)
        self.assertTrue(valid_formset.is_valid(), valid_formset.errors)

    def test_company_state_machine_db_unique_constraint(self):
        """Test database deferred UniqueConstraint raises IntegrityError on duplicate company_bot + step."""
        from django.db import IntegrityError, transaction, connection

        test_bot = CompanyBot.objects.create(
            name="Unique Bot", company=self.company, route="/unique-bot", context="Context"
        )
        CompanyStateMachine.objects.create(
            company_bot=test_bot, name="Step 10", step=10, operation_type=OperationTypeChoices.NON_LLM
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CompanyStateMachine.objects.create(
                    company_bot=test_bot, name="Step 10 Duplicate", step=10, operation_type=OperationTypeChoices.NON_LLM
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE;")

    def test_company_state_machine_step_swap_in_transaction(self):
        """Test that swapping two steps within an atomic transaction succeeds due to deferred constraint."""
        from django.db import transaction

        test_bot = CompanyBot.objects.create(
            name="Swap Bot", company=self.company, route="/swap-bot", context="Context"
        )
        step1 = CompanyStateMachine.objects.create(
            company_bot=test_bot, name="Step 1", step=1, operation_type=OperationTypeChoices.NON_LLM
        )
        step2 = CompanyStateMachine.objects.create(
            company_bot=test_bot, name="Step 2", step=2, operation_type=OperationTypeChoices.NON_LLM
        )

        with transaction.atomic():
            step1.step = 2
            step1.save()
            step2.step = 1
            step2.save()

        step1.refresh_from_db()
        step2.refresh_from_db()
        self.assertEqual(step1.step, 2)
        self.assertEqual(step2.step, 1)

    def test_non_llm_chat_view_starting_with_step_greater_than_one(self):
        """Test non_llm_chat_view correctly finds first step and advances for bots starting above step 1."""
        bot_offset = CompanyBot.objects.create(
            name="Offset Bot", company=self.company, route="/offset-bot", context="Context"
        )
        CompanyStateMachine.objects.create(
            company_bot=bot_offset,
            name="Step 5",
            step=5,
            operation_type=OperationTypeChoices.NON_LLM,
            bot_question="Step 5 question",
        )
        CompanyStateMachine.objects.create(
            company_bot=bot_offset,
            name="Step 7",
            step=7,
            operation_type=OperationTypeChoices.NON_LLM,
            bot_question="Step 7 question",
        )

        factory = APIRequestFactory()
        request = factory.post(
            "/api/non-llm-chat/",
            {
                "session": "test-session-offset-bot",
                "company_bot": bot_offset.id,
                "profile_id": self.profile.id,
                "message": "Start",
                "language": "en",
            },
            format="json",
        )

        response = non_llm_chat_view(request)
        self.assertEqual(response.status_code, 200)
        # Session started at lowest step (5) and advanced to step 7
        self.assertEqual(response.data["step"], 7)
        self.assertEqual(response.data["bot_message"], "Step 7 question")
        self.assertTrue(response.data["is_complete"])

        # Chat session should now be at step 7
        session = ChatSession.objects.get(session="test-session-offset-bot")
        self.assertEqual(session.current_step, 7)

    def test_shared_state_machine_steps_helper(self):
        """Test build_state_machine_steps_response returns complete ordered list."""
        from chatbot.utils.chat_utils import build_state_machine_steps_response

        steps = build_state_machine_steps_response(self.bot, language="en")
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["step"], 1)
        self.assertEqual(steps[0]["bot_question"], "Select role")
        self.assertIsNotNone(steps[0]["validations"])
        self.assertEqual(steps[1]["step"], 2)
        self.assertEqual(steps[1]["bot_question"], "Select grade")

    def test_bot_vernacular_view_with_target_language_and_steps(self):
        """Test BotVernacularListCreateView accepts target_language and returns state_machine_steps."""
        from chatbot.models import BotVernacular
        from chatbot.views.drf_views import BotVernacularListCreateView

        BotVernacular.objects.create(
            company_bot=self.bot,
            language="hi",
            name="Test Bot Hindi",
            introductory_message="Namaste",
        )

        factory = APIRequestFactory()
        view = BotVernacularListCreateView.as_view()

        # Query using target_language
        request = factory.get(f"/api/bot-vernacular/?company_bot__route={self.bot.route}&target_language=hi")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("state_machine_steps", response.data)
        self.assertEqual(len(response.data["state_machine_steps"]), 2)

