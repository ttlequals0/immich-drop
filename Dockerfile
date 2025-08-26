# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /immich_drop

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir python-multipart

# Copy app code
COPY . /immich_drop


# Data dir for SQLite (state.db)
RUN mkdir -p /data
VOLUME ["/data"]

# Defaults (can be overridden via compose env)
ENV HOST=0.0.0.0 \
    PORT=8080 \
    STATE_DB=/data/state.db

EXPOSE 8080

CMD ["python", "main.py"]
