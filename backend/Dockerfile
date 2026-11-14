# Backend image: used for the API, the worker and the one-shot migration job.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# FFmpeg/ffprobe for the technical check and rendering (Phase 7).
# PostgreSQL 16 client (same major version as the server) and GnuPG for the
# encrypted backups (Phase 15); the client comes from the official PGDG repository.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core gnupg postgresql-common \
 && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print('\n'.join(d['project']['dependencies']))" > /tmp/req.txt \
 && pip install -r /tmp/req.txt

COPY . .

RUN useradd --create-home --uid 10001 app && chown -R app /app \
    && mkdir -p /data/media /data/backups && chown app /data/media /data/backups
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
