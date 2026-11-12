# syntax=docker/dockerfile:1.4

# Multi-stage Dockerfile for FraiseQL Python Framework
# Optimized for production with security best practices

# Stage 1: Builder
#
# Alpine rather than Debian slim: every container-security alert on the slim
# image was a Debian base package with no upstream fix (libc, krb5, ldap,
# sqlite, util-linux...), which no rebuild can clear. The Alpine base carries a
# fraction of the packages, and its libpq needs only musl and OpenSSL.
FROM python:3.13-alpine AS builder

RUN apk upgrade --no-cache && apk add --no-cache \
    build-base \
    curl \
    libffi-dev \
    openssl-dev \
    postgresql-dev

# Install Rust (required for fraiseql_rs PyO3 extension)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src
COPY fraiseql_rs ./fraiseql_rs

# Build the FraiseQL wheel (Rust extension via maturin), then a wheelhouse of
# everything the runtime installs, so the runtime stage needs no compiler for
# a dependency without a musllinux wheel. psycopg's C implementation is built
# against Alpine's libpq: the pure-Python one finds libpq through
# ctypes.util.find_library, which cannot see it on musl.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    pip install build maturin && \
    python -m build --wheel --outdir /build/dist && \
    pip wheel --wheel-dir /build/wheels \
        /build/dist/*.whl \
        "psycopg[c]" \
        "uvicorn[standard]" \
        gunicorn \
        prometheus-client

# Stage 2: Runtime
FROM python:3.13-alpine AS runtime

LABEL org.opencontainers.image.authors="FraiseQL Team"
LABEL org.opencontainers.image.version="1.10.1"
LABEL org.opencontainers.image.description="FraiseQL — Python GraphQL framework with PostgreSQL and Rust acceleration"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/fraiseql/fraiseql-python"

# Install runtime dependencies and security updates
# libgcc: the Rust extension links libgcc_s dynamically on musl.
RUN apk upgrade --no-cache && apk add --no-cache libgcc libpq

# Create non-root user
RUN addgroup -S fraiseql && adduser -S -G fraiseql -H fraiseql

WORKDIR /app

# Installed from the builder's wheelhouse through a bind mount, so no wheel ever
# lands in an image layer. pip and setuptools are build tooling: the entrypoint
# is gunicorn, so nothing at runtime needs either. They are removed in the
# *same* layer -- a separate RUN would leave the old copies in the image
# history, where Trivy still finds them, along with pip's vendored packages.
RUN --mount=type=bind,from=builder,source=/build/wheels,target=/wheels \
    pip install --no-index --find-links /wheels \
    fraiseql \
    "psycopg[c]" \
    "uvicorn[standard]" \
    gunicorn \
    prometheus-client \
    && (pip uninstall -y pip setuptools 2>/dev/null || true)

# Copy entrypoint script
COPY deploy/docker/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

RUN chown -R fraiseql:fraiseql /app

USER fraiseql

EXPOSE 8000

# Probed with the interpreter that is already in the image. `curl` was the only
# reason the runtime stage installed it, and curl + libcurl + libssh2 account for
# ~40 of the container-security alerts on their own.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=2).status == 200 else 1)"]

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FRAISEQL_PRODUCTION=true

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "app:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
