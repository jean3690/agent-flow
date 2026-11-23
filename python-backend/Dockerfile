FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY python-backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY python-backend/app ./app
COPY python-backend/run.py ./run.py
COPY backend/src/main/resources/skills ./skills
COPY backend/src/main/resources/schema.sql ./schema.sql

RUN mkdir -p /app/audio_output \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8084

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=12 \
    CMD curl -fsS http://127.0.0.1:8084/api/node-types >/dev/null || exit 1

CMD ["python", "run.py"]
