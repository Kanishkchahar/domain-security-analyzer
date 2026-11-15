# ==============================================================================
# Multi-stage production build for Domain Security Analyzer
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Dependency Builder
# ------------------------------------------------------------------------------
ARG PYTHON_VERSION=3.11
ARG DEBIAN_SUITE=bookworm
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_SUITE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt pyproject.toml ./
COPY app ./app
COPY static ./static

# Build isolated virtual environment
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock.txt \
    && /opt/venv/bin/pip install --no-cache-dir --no-build-isolation --no-deps .

# ------------------------------------------------------------------------------
# Stage 2: Test gate. The runtime image depends on this stage, so a failed test
# suite makes the default image build fail. Dev tools never enter the runtime.
# ------------------------------------------------------------------------------
FROM builder AS test

COPY . ./

RUN /opt/venv/bin/pip install --no-cache-dir -r requirements-dev.txt \
    && /opt/venv/bin/pytest -q \
    && touch /tmp/domain-security-analyzer-tests-passed

# ------------------------------------------------------------------------------
# Stage 3: Production Runtime
# ------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_SUITE} AS runtime

ARG APP_VERSION=2.2.0
LABEL org.opencontainers.image.title="Domain Security Analyzer" \
      org.opencontainers.image.description="Domain and infrastructure security assessment dashboard and scanner" \
      org.opencontainers.image.source="https://github.com/Kanishkchahar/domain-security-analyzer" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

WORKDIR /app

# Copy isolated virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=test /tmp/domain-security-analyzer-tests-passed /tmp/domain-security-analyzer-tests-passed

# Nmap is optional at runtime but enables bounded service/version identification.
RUN apt-get update && apt-get install -y --no-install-recommends nmap ffuf \
    && command -v nmap >/dev/null \
    && command -v ffuf >/dev/null \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Security hardening: use a stable, unprivileged UID and avoid a recursive
# ownership-change layer by assigning ownership when application files copy.
RUN useradd --uid 10001 --create-home --home-dir /home/appuser \
    --shell /usr/sbin/nologin appuser
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 static ./static

USER 10001:10001

EXPOSE 8000

STOPSIGNAL SIGTERM

# Built-in lightweight health check (does not require external curl)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready', timeout=4).read()" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
