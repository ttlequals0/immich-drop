# syntax=docker/dockerfile:1.7
FROM python:3.14-slim

WORKDIR /immich_drop

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Pull in the latest debian security patches.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Static ffmpeg binary -- avoids dragging in mesa, libssh, libcups, libgbm,
# systemd, libmbedcrypto, etc. via the debian ffmpeg meta-package, every one
# of which has unpatched HIGH/CRITICAL CVEs in trixie. yt-dlp only uses the
# ffmpeg/ffprobe binaries, so a static build is functionally equivalent.
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:7.1 /ffprobe /usr/local/bin/ffprobe

# Install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir python-multipart

# Copy app code
COPY . /immich_drop

# Ensure all source files are readable (fix permission issues)
RUN chmod -R 644 /immich_drop/*.py /immich_drop/app/*.py /immich_drop/frontend/* && \
    chmod 755 /immich_drop /immich_drop/app /immich_drop/frontend

# Data dir for SQLite (state.db)
RUN mkdir -p /data
VOLUME ["/data"]

# Defaults (can be overridden via compose env)
ENV HOST=0.0.0.0 \
    PORT=8080 \
    STATE_DB=/data/state.db

EXPOSE 8080

CMD ["python", "main.py"]
