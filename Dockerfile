# Polyglot Swarm — application image (API + Gradio).
#
# Single image that can run either the FastAPI service or the Gradio UI; the
# compose files run it with different commands. Production hardening
# (ADR-0035): dependencies pinned by requirements.lock, a non-root user, a
# container healthcheck, and one uvicorn worker (SQLite single-writer and the
# in-process session cache; see docs/production/performance-report.md).

FROM python:3.12-slim AS base

# System deps: ffmpeg decodes uploaded audio (speech assessment, Whisper).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (better layer caching). requirements.lock is
# used as a *constraints* file: every runtime dependency is pinned to the
# locked version, but dev-only tools in the lock are not installed.
# Installed in editable mode so the code runs from /app: the language packs
# (/app/languages) and calibration maps (/app/evals/real/calibration) are
# found relative to the source tree, including by the `polyglot` command.
COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
RUN pip install -c requirements.lock -e .

# Bring in the rest (scenarios, language packs, frontend assets, ...).
COPY . .

# Data (SQLite + ChromaDB + profiles + media + backups) lives in /data and is
# volume-mounted. The app runs as an unprivileged user that owns only /data.
ENV DB_PATH=/data/polyglot.db \
    CHROMA_PATH=/data/chroma \
    PROFILES_DIR=/data/user_profiles \
    DATA_DIR=/data
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /data
USER app

EXPOSE 8000 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# Default: run the API. Compose overrides the command for the UI service.
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--timeout-graceful-shutdown", "30"]
