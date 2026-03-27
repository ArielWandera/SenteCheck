FROM python:3.11-slim

# Don't write .pyc files; flush stdout/stderr immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install OS-level deps needed by asyncpg and cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY alembic/ alembic/
COPY alembic.ini alembic.ini
COPY app/ app/

# Expose the port Uvicorn will listen on
EXPOSE 8000

# Railway sets PORT; fall back to 8000 for local docker-compose usage.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
