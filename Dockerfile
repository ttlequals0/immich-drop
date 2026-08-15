# syntax=docker/dockerfile:1.7
# ---- Builder Stage ----
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /install

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ---- Final Stage ----
FROM python:3.11-slim

# Pull in the latest debian security patches.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /immich_drop

# Copy static ffmpeg binaries
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:7.1 /ffprobe /usr/local/bin/ffprobe

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Create a non-root user
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /bin/bash -m appuser

# Copy app code
COPY . /immich_drop

# Create data directory and set permissions
RUN mkdir -p /data && \
    chown -R appuser:appuser /immich_drop /data

# Switch to non-root user
USER appuser

# Defaults (can be overridden via compose env)
ENV HOST=0.0.0.0 \
    PORT=8080 \
    STATE_DB=/data/state.db

EXPOSE 8080

CMD ["python", "main.py"]
