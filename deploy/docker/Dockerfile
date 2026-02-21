# syntax=docker/dockerfile:1.4

# Multi-stage Dockerfile for FraiseQL
# Optimized for production with security best practices

# Stage 1: Builder
FROM python:3.13-slim AS builder

# Install build dependencies and security updates
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    libssl-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Set working directory
WORKDIR /build

# Copy dependency files first for better caching
COPY pyproject.toml README.md ./
COPY src ./src
COPY fraiseql_rs ./fraiseql_rs

# Build fraiseql-confiture wheel first (no cp313-manylinux on PyPI yet)
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    pip install build maturin && \
    mkdir -p /build/dist && \
    pip download --no-deps --dest /tmp fraiseql-confiture>=0.1.0 && \
    cd /tmp && \
    tar -xzf fraiseql_confiture-*.tar.gz && \
    cd fraiseql_confiture-*/ && \
    python -m build --wheel && \
    mv dist/*.whl /build/dist/

# Build FraiseQL wheel
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    python -m build --wheel

# Stage 2: Runtime
FROM python:3.13-slim AS runtime

# Labels for metadata
LABEL org.opencontainers.image.authors="FraiseQL Team"
LABEL org.opencontainers.image.version="1.9.4"
LABEL org.opencontainers.image.description="Production-ready GraphQL-to-PostgreSQL framework with native Rust performance"

# Install runtime dependencies and security updates
# CVE Fixes: CVE-2025-14104, CVE-2025-6141, CVE-2024-56433
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r fraiseql && useradd -r -g fraiseql fraiseql

# Set working directory
WORKDIR /app

# Copy wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install FraiseQL and production dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    /tmp/*.whl \
    uvicorn[standard] \
    gunicorn \
    prometheus-client \
    opentelemetry-api \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi \
    opentelemetry-instrumentation-psycopg \
    && rm -rf /tmp/*.whl

# Copy entrypoint script
COPY deploy/docker/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Create app directory and set permissions
RUN mkdir -p /app && chown -R fraiseql:fraiseql /app

# Switch to non-root user
USER fraiseql

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRAISEQL_PRODUCTION=true

# Entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command - can be overridden
CMD ["gunicorn", "app:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]

# Security scanning recommendation
# To scan this image for vulnerabilities, run:
# docker run --rm -i hadolint/hadolint < Dockerfile
# trivy image fraiseql:latest
