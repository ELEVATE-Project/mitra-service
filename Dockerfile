FROM python:3.11-slim

# uv installs dependencies from uv.lock - the same lockfile the Ansible deploy
# uses (`uv sync --frozen`), so the image and the servers get identical packages.
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
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    g++ \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app/backend

# Install Python dependencies first (only the lockfile is copied) so this layer
# stays cached until dependencies change. Dev group (stubs, ruff) is skipped.
COPY pyproject.toml uv.lock /app/backend/
RUN uv sync --frozen --no-dev --no-install-project --no-cache

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
