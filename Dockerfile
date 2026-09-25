FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build arg to force rebuild when code changes
ARG BUILD_DATE=unknown
ARG GIT_COMMIT=unknown

WORKDIR /code

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY alembic ./alembic
COPY alembic.ini ./
COPY app ./app

RUN pip install --no-cache-dir -e . && pip install --no-cache-dir asyncpg uvicorn[standard]

CMD ["python", "-m", "app.main"]
