FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    pgbouncer \
    cron \
    logrotate \
    gcc \
    g++ \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv and verify the binary actually works
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
RUN uv --version

WORKDIR /app/backend

# Copy project files (pyproject.toml has no [tool.uv] package=false, so `uv sync`
# self-installs the project and needs README.md + source present, not just the manifests)
COPY . /app/backend

# Create the venv and put it on PATH — equivalent of `source .venv/bin/activate`
# for every later RUN/CMD, since each RUN is its own shell and a literal `source`
# would not persist across layers.
RUN uv venv .venv
ENV VIRTUAL_ENV="/app/backend/.venv" \
    PATH="/app/backend/.venv/bin:${PATH}"

RUN uv sync --frozen

RUN chmod +x /app/backend/docker/entrypoint.sh

# Create logs directory
RUN mkdir -p /app/backend/logs

# pgbouncer log rotation (daily, 3-day retention); picked up automatically
# by Debian's default /etc/cron.daily/logrotate run
COPY infra/pgbouncer.logrotate /etc/logrotate.d/pgbouncer

# Create directory for static files
RUN mkdir -p /var/www/shikshalokam/static

# Expose port (default Django development server port, adjust as needed)
EXPOSE 9000

WORKDIR /app/backend

# Starts a local PgBouncer, points DATABASE_HOST/PORT at it, then execs the real command
ENTRYPOINT ["docker/entrypoint.sh"]

# Default command - can be overridden in docker-compose or run command
# For production, you might want to use daphne or gunicorn
CMD ["uvicorn", "shikshalokam_mohini.asgi:application", "--host", "0.0.0.0", "--port", "9000", "--workers", "4", "--ws-ping-interval", "30", "--ws-ping-timeout", "600"]