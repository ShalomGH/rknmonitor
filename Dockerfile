FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY deploy/ ./deploy/
COPY docker-compose.agent.public.yml ./docker-compose.agent.public.yml
COPY alembic.ini .
COPY README.md .
COPY RUNBOOK.md .

ENV PYTHONPATH=/app/src

CMD ["uvicorn", "rknmon.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
