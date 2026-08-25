# syntax=docker/dockerfile:1.7
FROM python:3.14-alpine

WORKDIR /immich_drop

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Pull in the latest security patches.
RUN apk upgrade --no-cache

# Static ffmpeg binary -- avoids the distro ffmpeg package and its dependency
# tree. yt-dlp only uses the ffmpeg/ffprobe binaries.
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:7.1 /ffprobe /usr/local/bin/ffprobe

# Install Python deps
COPY requirements.txt /immich_drop/requirements.txt
# pip is removed after install: the runtime never uses it, and its vendored
# msgpack/pkg_resources copies are the only CVE hits in the python layer
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /immich_drop/requirements.txt \
    && pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.11/ensurepip

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

# /api/config never redirects; / 302s to /login when the public page is off
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD python -c 'import os,urllib.request; urllib.request.urlopen("http://127.0.0.1:%s/api/config" % os.getenv("PORT","8080"), timeout=3).read()'

CMD ["python", "main.py"]
