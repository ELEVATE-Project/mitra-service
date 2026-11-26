
import logging
import os

from django.core.exceptions import ImproperlyConfigured

from config.env_schema import ENV_SCHEMA

logger = logging.getLogger(__name__)

_validated = False
VALID_REQUIRED_IF_OPERATORS = ("EQUALS", "NOT_EQUALS")


def _is_required(spec):
    if not spec.get("optional", False):
        return True

    condition = spec.get("requiredIf")
    if not condition or not condition.get("key") or not condition.get("value"):
        return False

    actual = os.environ.get(condition["key"], "")
    operator = condition.get("operator")

    if operator == "EQUALS":
        return actual == condition["value"]

    if operator == "NOT_EQUALS":
        return actual != condition["value"]

    return False


def validate_env(schema=ENV_SCHEMA):
    """Check every schema entry. Applies defaults, returns a list of errors."""
    rows, errors = [], []

    for name, spec in schema.items():
        value = (os.environ.get(name) or "").strip()
        problem = None

        if _is_required(spec):
            if not value:
                problem = spec.get("message") or f"{name} is required"

        elif not value and "default" in spec:
            os.environ[name] = str(spec["default"])
            value = os.environ[name]

        possible = spec.get("possible_values")

        if problem is None and value and possible:
            match = next(
                (p for p in possible if p.lower() == value.lower()),
                None,
            )

            if match is None:
                problem = (
                    f"{spec.get('message', name)} "
                    f"Valid values: {', '.join(possible)}"
                )
            else:
                # Normalize accepted values to their canonical form.
                os.environ[name] = match
                value = match

        if problem:
            errors.append(f"{name}: {problem}")
            rows.append((name, f"FAILED - {problem}"))
        else:
            rows.append((name, "PASSED"))

    width = max((len(name) for name, _ in rows), default=0)
    table = "\n".join(
        f"{name.ljust(width)}  {status}"
        for name, status in rows
    )

    logger.info("Environment validation:\n%s", table)

    return errors


def ensure_env_validated():
    """Runs validation once per process. Raises if anything is missing."""
    global _validated

    if _validated:
        return

    errors = validate_env()

    if errors:
        raise ImproperlyConfigured(
            "Environment validation failed:\n  - "
            + "\n  - ".join(errors)
        )

    _validated = True


class EnvConfigMiddleware:
    """
    Validates environment config when the middleware chain loads at startup.
    Per-request overhead is a passthrough.
    """

    def __init__(self, get_response):
        ensure_env_validated()
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)
