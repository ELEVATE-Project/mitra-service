FROM python:3.11-slim

# uv installs dependencies the same way the Ansible deploy ends up doing: it
# syncs uv.lock, and if pyproject.toml has changed without uv.lock being
# updated, it re-locks from pyproject.toml first (on the servers this happens
# via the un-frozen `uv run ... migrate` step).
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

# Install system dependencies
# ffmpeg: converts uploaded audio to 16 kHz mono WAV for /api/asr/
#   (chatbot/utils/audio_converter_utils.py runs the `ffmpeg` binary) and is
#   the backend pydub uses for non-WAV audio. Not a Python package, so it must
#   be installed here; see system_dependencies.md.
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    g++ \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Fail the build early if ffmpeg is missing, instead of failing on the first
# voice message in a running pod.
RUN ffmpeg -version > /dev/null

# Set working directory
WORKDIR /app/backend

# Install Python dependencies first (only the lockfile is copied) so this layer
# stays cached until dependencies change. Dev group (stubs, ruff) is skipped.
COPY pyproject.toml uv.lock /app/backend/
RUN uv sync --no-dev --no-install-project --no-cache

# Copy project files
COPY . /app/backend

# Create logs directory
RUN mkdir -p /app/backend/logs

# Create directory for static files
RUN mkdir -p /var/www/shikshalokam/static

# Expose port (default Django development server port, adjust as needed)
EXPOSE 9000

# Default command - can be overridden in docker-compose or run command
# For production, you might want to use daphne or gunicorn
CMD ["uvicorn", "shikshalokam_mohini.asgi:application", "--host", "0.0.0.0", "--port", "9000", "--workers", "4", "--ws-ping-interval", "30", "--ws-ping-timeout", "600"]