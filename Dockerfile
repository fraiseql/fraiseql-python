# syntax=docker/dockerfile:1.4

# Multi-stage Dockerfile for FraiseQL Python Framework
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

# Install Rust (required for fraiseql_rs PyO3 extension)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Set working directory
WORKDIR /build

# Copy dependency files first for better caching
COPY pyproject.toml README.md ./
COPY src ./src
COPY fraiseql_rs ./fraiseql_rs

# Build FraiseQL wheel (includes Rust extension via maturin)
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    pip install build maturin && \
    mkdir -p /build/dist && \
    python -m build --wheel

# Stage 2: Runtime
FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.authors="FraiseQL Team"
LABEL org.opencontainers.image.version="1.10.1"
LABEL org.opencontainers.image.description="FraiseQL — Python GraphQL framework with PostgreSQL and Rust acceleration"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/fraiseql/fraiseql-python"

# Install runtime dependencies and security updates
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r fraiseql && useradd -r -g fraiseql fraiseql

WORKDIR /app

# Copy wheel from builder and install
COPY --from=builder /build/dist/*.whl /tmp/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    /tmp/*.whl \
    uvicorn[standard] \
    gunicorn \
    prometheus-client \
    && rm -rf /tmp/*.whl

# Copy entrypoint script
COPY deploy/docker/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

RUN chown -R fraiseql:fraiseql /app

USER fraiseql

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRAISEQL_PRODUCTION=true

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "app:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
