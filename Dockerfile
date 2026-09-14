# Polyglot Swarm — application image (API + Gradio).
#
# Single image that can run either the FastAPI service or the Gradio UI; the
# docker-compose stack runs both from this image with different commands.

FROM python:3.12-slim AS base

# System deps: ffmpeg is needed by Whisper for audio decoding (voice extra).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching). Copy only what the build
# backend needs to resolve metadata, then the source.
COPY pyproject.toml README.md ./
COPY src ./src

# Install the project (base deps only; add [voice] for STT/TTS/LiveKit).
RUN pip install --upgrade pip && pip install .

# Bring in the rest (scenarios data, frontend, etc.).
COPY . .

# Data (SQLite + ChromaDB + profiles) lives here and is volume-mounted.
ENV DB_PATH=/data/polyglot.db \
    CHROMA_PATH=/data/chroma \
    PROFILES_DIR=/data/user_profiles \
    DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000 7860

# Default: run the API. Compose overrides the command for the UI service.
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
