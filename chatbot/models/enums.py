from random import choices

from django.db import models
from django.utils.translation import gettext_lazy as _


class ChatStatus(models.TextChoices):
    STARTED = 'STARTED', _('STARTED')
    IN_PROGRESS = 'IN_PROGRESS', _('IN_PROGRESS')
    COMPLETED = 'COMPLETED', _('COMPLETED')
    PAUSED = 'PAUSED', _('PAUSED')
    RESUME = 'RESUME', _('RESUME')


class ChatType(models.TextChoices):
    guidedReflection = 'normal', _('Guided Reflection')
    oneStepReflection = 'oneshot', _('One Step Reflection')
    shikshaChaupal = 'shikshalokam_chaupal', _('Shiksha Chaupal')
    reflection = 'reflection', _('Reflection')
    creation = 'creation', _('Creation')
    megaPTM = 'megaPTM', _('Mega PTM')


class LLMProvider(models.TextChoices):
    BEDROCK = 'bedrock', _('BEDROCK')
    BEDROCK_CONVERSE = 'bedrock/converse', _('BEDROCK_CONVERSE')
    OPENAI = 'openai', _('OPENAI')

class LLMModel(models.TextChoices):
    GPT4 = 'gpt-4', _('GPT4')
    GPT4_1 = 'gpt-4.1', _('GPT4_1')
    GPT4_1_MINI = 'gpt-4.1-mini', _('GPT4_1-MINI')
    GPT4_128K = 'gpt-4-1106-preview', _('GPT4-128k')
    GPT4_TURBO = 'gpt-4-turbo', _('GPT4_TURBO')
    LLAMA_3_8B_8192 = 'llama3-8b-8192', _('LLAMA_3_8B_8192')
    LLAMA_3_70B_8192 = 'llama3-70b-8192', _('LLAMA_3_70B_8192')
    LLAMA_3_1_70B_VERSATILE = 'llama-3.1-70b-versatile', _('LLAMA_3_1_70B_VERSATILE')
    LLAMA_3_1_8B_INSTANT = 'llama-3.1-8b-instant', _('LLAMA_3_1_8B_INSTANT')
    LLAMA_3_1_70B_INSTRUCT = 'meta.llama3-1-70b-instruct-v1:0', _('LLAMA_3_1_70B_INSTRUCT')
    LLAMA_3_1_8B_INSTRUCT = 'meta.llama3-1-8b-instruct-v1:0', _('LLAMA_3_1_8B_INSTRUCT')
    LLAMA_3_3_70B_INSTRUCT = 'us.meta.llama3-3-70b-instruct-v1:0', _('LLAMA_3_3_70B_INSTRUCT')
    LLAMA_3_3_8B_INSTRUCT = 'us.meta.llama3-3-8b-instruct-v1:0', _('LLAMA_3_3_8B_INSTRUCT')
    MIXTRAL_8X70B_32768 = 'mixtral-8x7b-32768', _('MIXTRAL_8X70B_32768')
    GPT4_O = 'gpt-4o', _('GPT4_O')
    GPT4_O_MINI = 'gpt-4o-mini', _('GPT4_O_MINI')
    LLAMA_3_1_8B_OPS = 'meta-llama/Meta-Llama-3.1-8B-Instruct', _('meta-llama/Meta-Llama-3.1-8B-Instruct')


class EntityStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', _('ACTIVE')
    INACTIVE = 'INACTIVE', _('INACTIVE')


class ProfileType(models.TextChoices):
    USER = 'USER', _('USER')
    MODERATOR = 'MODERATOR', _('MODERATOR')
    PROSPECT = 'PROSPECT', _('PROSPECT')


class FeedbackChoices(models.TextChoices):
    POSITIVE = 'POSITIVE', _('POSITIVE')
    NEGATIVE = 'NEGATIVE', _('NEGATIVE')


class GenderChoices(models.TextChoices):
    MALE = 'Male', _('Male')
    FEMALE = 'Female', _('Female')


class LanguageChoices(models.TextChoices):
    INDIAN_ENGLISH = 'en-IN', _('INDIAN ENGLISH')
    INDIAN_HINDI = 'hi-IN', _('INDIAN HINDI')
    US_ENGLISH = 'en-US', _('US ENGLISH')
    INDIAN_KANNADA = 'kn-IN', _('INDIAN KANNADA')


class MediaTypeChoices(models.TextChoices):
    PDF = 'application/pdf', _('PDF')
    TXT = 'text/plain', _('TXT')
    CSV = 'text/csv', _('CSV')
    JPEG = 'image/jpeg', _('JPEG')
    PNG = 'image/png', _('PNG')
    SVG = 'image/svg+xml', _('SVG')
    WEBP = 'image/webp', _('WEBP')
    HEIF = 'image/heif', _('HEIF')
    HEIC = 'image/heic', _('HEIC')


class VoiceProviderChoices(models.TextChoices):
    AWS = 'aws', _('AWS')
    GCP = 'gcp', _('GCP')
    AZURE = 'azure', _('Azure')
    ELEVEN_LABS = 'eleven-labs', _('Eleven Labs')



class ChatStageChoices(models.TextChoices):
    WELCOME = 'Welcome_Strand', _('WELCOME_STRAND')
    ACHIEVEMENT_ORIENTATION = 'Achievement_Orientation', _('ACHIEVEMENT_ORIENTATION')
    COURAGE = 'Courage_Strand', _('COURAGE_STRAND')
    CONTINUOUS_LEARNING = 'Continuous_Strand', _('CONTINUOUS_STRAND')
    CRITICAL_THINKING = 'Critical_Thinking_Strand', _('CRITICAL_THINKING_STRAND')
    PURPOSE = 'Purpose_Strand', _('PURPOSE_STRAND')
    THANKYOU = 'Thank_You_Strand', _('THANK_YOU_STRAND')
    OTHER = 'Other', _('OTHER')


class TagChoices(models.TextChoices):
    APPROVED = 'Approved', _('Approved')
    PENDING = 'Pending', _('Pending')


class StoryLanguageChoices(models.TextChoices):
    ENGLISH = 'en', _('English')
    HINDI = 'hi', _('Hindi')
    KANNADA = 'kn', _('Kannada')
    TELUGU = 'te', _('Telugu')


class StorySourceChoices(models.TextChoices):
    AI_GENERATED = 'AI_GENERATED', _('AI_GENERATED')
    USER_GENERATED = 'USER_GENERATED', _('USER_GENERATED')
    THIRD_PARTY = 'THIRD_PARTY', _('THIRD_PARTY')


class StoryStatusChoices(models.TextChoices):
    PENDING = 'PENDING', _('PENDING')
    COMPLETED = 'COMPLETED', _('COMPLETED')


class EntityTypeChoices(models.TextChoices):
    MANDATORY = 'MANDATORY', _('MANDATORY')
    OPTIONAL = 'OPTIONAL', _('OPTIONAL')


class CompanyBotTypeChoices(models.TextChoices):
    SIMPLE = 'SIMPLE', _('SIMPLE')
    STATE_MACHINE = 'STATE_MACHINE', _('STATE_MACHINE')
    DATABASE_SIMPLE = 'DATABASE_SIMPLE', _('DATABASE_SIMPLE')
    INTERVIEW_STATE_MACHINE = 'INTERVIEW_STATE_MACHINE', _('INTERVIEW_STATE_MACHINE')


class CompanyBotDynamicContextType(models.TextChoices):
    SQL_QUERY = 'SQL_QUERY', _('SQL_QUERY')
    PYTHON_SCRIPT = 'PYTHON_SCRIPT', _('PYTHON_SCRIPT')


class CompanyChatSourceChoices(models.TextChoices):
    WEB = 'WEB', _('WEB')
    PHONE = 'PHONE', _('PHONE')


class RouteLanguageChoices(models.TextChoices):
    ENGLISH = 'en', _('/')
    HINDI = 'hi', _('/hindi')
    KANNADA = 'kn', _('/kannada')
    TELUGU = 'te', _('/telugu')


class VoiceProvider(models.TextChoices):
    GOOGLE = 'GOOGLE', _('GOOGLE')
    GOOGLE_V1 = 'GOOGLE_V1', _('GOOGLE v1 STT')
    AI4Bharat = 'AI4Bharat', _('AI4Bharat')
    OPENAI_WHISPER = 'OPENAI_WHISPER', _('OpenAI Whisper')
    SARVAM = 'Sarvam', _('Sarvam')


class VoiceType(models.TextChoices):
    SpeechToText = 'SpeechToText', _('Speech To Text')
    TextToText = 'TextToText', _('Text To Text')
    TextToSpeech = 'TextToSpeech', _('Text To Speech')
    Transliterate = 'Transliterate', _('Transliteration')


class LanguageMapping:
    MAPPING = {
        "en": {"IN": "en-IN", "US": "en-US"},
        "hi": {"IN": "hi-IN"},
        "kn": {"IN": "kn-IN"},
        "te": {"IN": "te-IN"},
    }

    @classmethod
    def get_mapped_language(cls, language_code: str, region: str = "IN") -> str:
        return cls.MAPPING.get(language_code, {}).get(region, f"{language_code}-IN")


class MediaTemplateChoices(models.TextChoices):
    EJS = 'EJS', _('EJS')
    RAW_TEXT = 'RAW-TEXT', _('RAW-TEXT')


class PDFStrategyChoices(models.TextChoices):
    HTMLPDF = 'HTMLPDF', _('HTMLPDF')
    PUPPETEER = 'PUPPETEER', _('PUPPETEER')
    HTMLDOCX = 'HTMLDOCX', _('HTMLDOCX')
    XLSX = 'XLSX', _('XLSX')


class SessionFlowName(models.TextChoices):
    GuestDiscussion = 'guest-discussion', _('guest-discussion')
    LoginDiscussion = 'login-discussion', _('login-discussion')
    GuestMiStory = 'guest-mi-story', _('guest-mi-story')
    LoginMiStory = 'login', _('login')
    Reflection = 'reflection', _('reflection')
    megaPTM = 'megaPTM', _('Mega PTM')
