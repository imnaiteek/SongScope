# SongScope API + worker image (same image, different command)
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NUMBA_CACHE_DIR=/tmp/numba-cache

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 nodejs \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY audio-engine /app/audio-engine
COPY backend /app/backend

ARG INSTALL_STEMS=false
RUN pip install /app/audio-engine /app/backend \
 && if [ "$INSTALL_STEMS" = "true" ]; then \
      pip install --extra-index-url https://download.pytorch.org/whl/cpu torch demucs; \
    fi

# Unprivileged runtime user; audio is processed in /data (a volume shared by api and worker)
RUN useradd --create-home --uid 10001 songscope && mkdir -p /data && chown songscope /data
USER songscope
ENV SONGSCOPE_DATA_DIR=/data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["uvicorn", "songscope_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
