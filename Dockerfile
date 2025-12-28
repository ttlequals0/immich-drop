# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /immich_drop

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies (ffmpeg for yt-dlp video processing)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir python-multipart

# Copy app code
COPY . /immich_drop

# Ensure Python files are readable (fix permission issues with volume mounts)
RUN chmod -R 644 /immich_drop/*.py /immich_drop/app/*.py && \
    chmod 755 /immich_drop /immich_drop/app

# Data dir for SQLite (state.db)
RUN mkdir -p /data
VOLUME ["/data"]

# Defaults (can be overridden via compose env)
ENV HOST=0.0.0.0 \
    PORT=8080 \
    STATE_DB=/data/state.db

EXPOSE 8080

CMD ["python", "main.py"]
