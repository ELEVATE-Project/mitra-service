
def req(message, **extra):
    return {"message": message, "optional": False, **extra}


def opt(message, default=None, **extra):
    spec = {"message": message, "optional": True, **extra}
    if default is not None:
        spec["default"] = default
    return spec


def required_if(message, key, value, **extra):
    return {
        "message": message,
        "optional": True,
        "requiredIf": {
            "key": key,
            "operator": "EQUALS",
            "value": value,
        },
        **extra,
    }


ON_OFF = ["ON", "OFF"]
TRUE_FALSE = ["True", "False"]
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
STORAGE_PROVIDERS = ["AWS", "GCP", "AZURE", "LOCAL"]


ENV_SCHEMA = {
    # Django core
    "DJANGO_SECRET_KEY": opt("Required Django secret key"),
    "DJANGO_SETTINGS_MODULE": opt(
        "Settings module path",
        default="shikshalokam_mohini.settings",
    ),
    "SETTINGS_DEBUG": opt(
        "Debug flag",
        default="False",
        possible_values=TRUE_FALSE,
    ),
    "ALLOWED_HOSTS": req("Comma-separated allowed hosts"),
    "CORS_ALLOWED_ORIGINS": opt(
        "Comma-separated CORS origins",
        default="",
    ),
    "CSRF_TRUSTED_ORIGINS": opt("Comma-separated CSRF trusted origins"),
    "DEFAULT_LOG_LEVEL": opt(
        "Log level",
        default="INFO",
        possible_values=LOG_LEVELS,
    ),
    "LOGGING_DIR": opt("Directory for log files", default="logs"),
    "STATIC_ROOT": opt(
        "Static files root",
        default="/var/www/shikshalokam/static/",
    ),
    "SENTRY_DSN": opt("Sentry DSN (blank disables Sentry)", default=""),
    "SENTRY_TRACES_SAMPLE_RATE": opt(
        "Sentry traces sample rate",
        default="0.1",
    ),
    "SENTRY_PROFILES_SAMPLE_RATE": opt(
        "Sentry profiles sample rate",
        default="0.1",
    ),

    # Auth
    "ELEVATE_BASE_URL": req("Elevate base URL"),
    "JWT_ALGORITHM": req(
        "JWT algorithm: HS256 (shared secret) or RS256 (public key)",
        possible_values=["HS256", "RS256"],
    ),
    "ACCESS_TOKEN_SECRET": required_if(
        "Access token secret is required for HS256",
        "JWT_ALGORITHM",
        "HS256",
    ),
    "JWT_PUBLIC_KEY": required_if(
        "Keycloak RS256 public key is required for RS256",
        "JWT_ALGORITHM",
        "RS256",
    ),

    # Database (PgBouncer)
    "PGBOUNCER_DATABASE_HOST": req("PgBouncer database host"),
    "PGBOUNCER_DATABASE_PORT": req("PgBouncer database port"),
    "PGBOUNCER_DATABASE_NAME": req("Database name"),
    "PGBOUNCER_DATABASE_USER": req("Database user"),
    "PGBOUNCER_DATABASE_PASSWORD": req("Database password"),
    "PG_SSL_MODE": opt("Postgres sslmode", default="prefer"),
    "PG_SSL_ROOT_CERT": required_if(
        "Root cert path, required for verify-full",
        "PG_SSL_MODE",
        "verify-full",
    ),

    # Source database (used by the source_db alias)
    "SOURCE_DATABASE_HOST": opt("Source DB host"),
    "SOURCE_DATABASE_PORT": opt("Source DB port"),
    "SOURCE_DATABASE_NAME": opt("Source DB name"),
    "SOURCE_DATABASE_USER": opt("Source DB user"),
    "SOURCE_DATABASE_PASSWORD": opt("Source DB password"),

    # Redis and Celery
    "REDIS_HOST": opt("Redis host"),
    "REDIS_PORT": opt("Redis port", default="6379"),
    "REDIS_USE_SSL": opt(
        "Use TLS for Redis",
        default="False",
        possible_values=TRUE_FALSE,
    ),
    "REDIS_SSL_CERT_REQS": opt(
        "Redis SSL cert requirement",
        default="CERT_NONE",
    ),
    "REDIS_CELERY_DB": opt("Redis DB index for Celery", default="2"),
    "CELERY_TASK_DEFAULT_QUEUE": opt(
        "Default Celery queue",
        default="mitra_service_queue",
    ),

    # Storage
    "STORAGE_CLOUD_PROVIDER": req(
        "Storage provider",
        possible_values=STORAGE_PROVIDERS,
    ),
    "AWS_ACCESS_KEY_ID": required_if(
        "AWS access key, required for AWS storage",
        "STORAGE_CLOUD_PROVIDER",
        "AWS",
    ),
    "AWS_SECRET_ACCESS_KEY": required_if(
        "AWS secret key, required for AWS storage",
        "STORAGE_CLOUD_PROVIDER",
        "AWS",
    ),
    "AWS_REGION": required_if(
        "AWS region, required for AWS storage",
        "STORAGE_CLOUD_PROVIDER",
        "AWS",
    ),
    "S3_BUCKET_NAME": required_if(
        "S3 bucket, required for AWS storage",
        "STORAGE_CLOUD_PROVIDER",
        "AWS",
    ),
    "S3_BASE_URL": opt("S3 base URL"),
    "S3_MEDIA_URL": opt("S3 media URL"),
    "MEDIA_BASE_URL": opt("Media base URL"),
    "GCS_BUCKET_NAME": required_if(
        "GCS bucket, required for GCP storage",
        "STORAGE_CLOUD_PROVIDER",
        "GCP",
    ),
    "GCP_PROJECT_ID": required_if(
        "GCP project ID, required for GCP storage",
        "STORAGE_CLOUD_PROVIDER",
        "GCP",
    ),
    "GCP_CREDENTIALS_PATH": required_if(
        "GCP credentials path, required for GCP storage",
        "STORAGE_CLOUD_PROVIDER",
        "GCP",
    ),
    "AZURE_ACCOUNT_NAME": required_if(
        "Azure account name, required for Azure storage",
        "STORAGE_CLOUD_PROVIDER",
        "AZURE",
    ),
    "AZURE_ACCOUNT_KEY": required_if(
        "Azure account key, required for Azure storage",
        "STORAGE_CLOUD_PROVIDER",
        "AZURE",
    ),
    "AZURE_CONTAINER_NAME": required_if(
        "Azure container, required for Azure storage",
        "STORAGE_CLOUD_PROVIDER",
        "AZURE",
    ),
    "GOOGLE_APPLICATION_CREDENTIALS": opt(
        "Path to GCP service account JSON",
    ),
    "SG_REPO_AWS_ACCESS_KEY_ID": opt(
        "Separate AWS key for the SG repo",
    ),
    "SG_REPO_AWS_SECRET_ACCESS_KEY": opt(
        "Separate AWS secret for the SG repo",
    ),

    # Internal services
    "SHIKSHALOKAM_BASE_URL": opt("Shikshalokam service URL"),
    "SSO_REROUTE_URL": opt("SSO reroute URL"),
    "LOCATION_BASE_URL": opt("Location service URL"),
    "LOCATION_AUTH": opt("Location service auth"),
    "RECOMMENDATION_BASE_URL": opt("Recommendation service URL"),
    "VECTOR_DB_BASE_URL": opt("Vector DB service URL"),
    "GOTENBERG_URL": opt("Gotenberg URL for PDF generation"),

    # LLM and speech providers
    "OPENAI_API_KEY": opt("OpenAI API key"),
    "SARVAM_API_KEY": opt("Sarvam API key"),
    "LLAMA_BASE_URL": opt("Llama base URL"),
    "LLAMA_HF_TOKEN": opt("Hugging Face token"),
    "LLAMAFINETUNE_BASE_URL": opt("Llama fine-tune base URL"),
    "LLM_RETRY_NUMBER": opt("LLM retry count", default="3"),
    "BHASHANI_BASE_URL": opt("Bhashini base URL"),
    "BHASHANI_API_KEY": opt("Bhashini API key"),
    "BHASHANI_AUTHORIZATION": opt("Bhashini authorization"),
    "BHASHANI_PIPELINE_ID": opt("Bhashini pipeline ID"),
    "BHASHANI_USER_ID": opt("Bhashini user ID"),

    # Langfuse
    "LANGFUSE_ENABLED": opt(
        "Enable/disable Langfuse tracing",
        default="OFF",
        possible_values=ON_OFF,
    ),
    "LANGFUSE_HOST": opt(
        "Langfuse host",
        default="https://cloud.langfuse.com",
    ),
    "LANGFUSE_PUBLIC_KEY": required_if(
        "Required when Langfuse is ON",
        "LANGFUSE_ENABLED",
        "ON",
    ),
    "LANGFUSE_SECRET_KEY": required_if(
        "Required when Langfuse is ON",
        "LANGFUSE_ENABLED",
        "ON",
    ),
}
