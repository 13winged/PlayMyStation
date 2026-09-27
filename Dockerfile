FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build arg to force rebuild when code changes
ARG BUILD_DATE=unknown
ARG GIT_COMMIT=unknown

WORKDIR /code

# Node 22+ нужен yt-dlp-ejs для решения n-сигнатур YouTube (дебиановский Node 20 не тянет).
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg gcc libpq-dev && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /etc/apt/keyrings \
  && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
  && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
  && apt-get update && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY alembic ./alembic
COPY alembic.ini ./
COPY app ./app

RUN pip install --no-cache-dir -e . && pip install --no-cache-dir asyncpg uvicorn[standard]

CMD ["python", "-m", "app.main"]
