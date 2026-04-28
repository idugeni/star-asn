# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.13-slim

FROM ${PYTHON_IMAGE} AS base

# Security: Non-root user configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_GC=1 \
    PATH=/opt/venv/bin:$PATH \
    # Security: Python security settings
    PYTHONHASHSEED=random

WORKDIR /app


FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN python -m venv /opt/venv
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .
RUN --mount=type=cache,target=/root/.cache/ms-playwright \
    python -m playwright install chromium


FROM base AS runtime

LABEL org.opencontainers.image.title="star-asn" \
      org.opencontainers.image.description="Telegram-only Star ASN runtime" \
      org.opencontainers.image.vendor="STAR-ASN"

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    libgl1 \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Security: Create non-root user with minimal permissions
RUN groupadd -r --gid=1000 appuser && \
    useradd -r --uid=1000 --gid=appuser --home=/app --shell=/bin/false appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /ms-playwright /ms-playwright

# Security: Set proper ownership
RUN chown -R appuser:appuser /opt/venv /ms-playwright /app

COPY --chown=appuser:appuser api ./api
COPY --chown=appuser:appuser star_attendance ./star_attendance
COPY --chown=appuser:appuser supabase ./supabase
COPY --chown=appuser:appuser pyproject.toml ./pyproject.toml
COPY --chown=appuser:appuser main.py ./main.py

# Security: Switch to non-root user
USER appuser

# Security: Read-only filesystem configuration hints
# Note: Runtime should mount /tmp and /var/tmp as tmpfs if needed

ENTRYPOINT ["python", "-m", "star_attendance.service_runner"]
CMD ["api"]

# Security metadata labels
LABEL org.opencontainers.image.source="https://github.com/idugeni/star-asn" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}"
