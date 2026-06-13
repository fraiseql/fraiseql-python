# FraiseQL Docker Configuration

This directory contains Docker configurations for FraiseQL deployment and testing environments.

## 📂 Docker Files

### `Dockerfile`

**Production deployment container**

- Multi-stage build for optimal image size
- Production-ready Python environment
- Security-hardened base image
- Minimal attack surface

### `Dockerfile.test`

**Testing environment container**

- Includes test dependencies
- PostgreSQL client tools
- Development utilities
- Test database configuration

### `Dockerfile.test-all-in-one`

**Complete testing environment with services**

- PostgreSQL database included
- Redis for caching (if needed)
- All testing tools pre-installed
- Self-contained testing environment

### `.dockerignore`

**Docker build context optimization**

- Excludes unnecessary files from build context
- Reduces build time and image size
- Security: excludes sensitive files

## 🚀 Usage

### Development

```bash
# Build development image
docker build -f deploy/docker/Dockerfile.test -t fraiseql:dev .

# Run with mounted source
docker run -v $(pwd):/app -p 8000:8000 fraiseql:dev
```

### Testing

```bash
# Build test environment
docker build -f deploy/docker/Dockerfile.test-all-in-one -t fraiseql:test .

# Run test suite
docker run --rm fraiseql:test pytest tests/
```

### Production

```bash
# Build production image
docker build -f deploy/docker/Dockerfile -t fraiseql:latest .

# Run production container
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://... \
  fraiseql:latest
```

## 🔧 Configuration

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection (optional)
- `LOG_LEVEL`: Logging level (INFO, DEBUG, etc.)
- `WORKERS`: Number of worker processes

### Volumes

- `/app/logs`: Application logs
- `/app/data`: Persistent data (if applicable)

## 📊 Image Sizes

- **Production**: ~100MB (Alpine-based)
- **Test**: ~200MB (includes dev dependencies)
- **All-in-one**: ~400MB (includes PostgreSQL)

## Prometheus monitoring with postgres_exporter

FraiseQL includes a custom queries config for
[postgres_exporter](https://github.com/prometheus-community/postgres_exporter)
at `postgres_exporter_queries.yml`. This exposes `pg_stat_statements` metrics
via the `v_query_stats` view.

### Setup

Add postgres_exporter to your `docker-compose.yml`:

```yaml
postgres-exporter:
  image: prometheuscommunity/postgres-exporter:latest
  environment:
    DATA_SOURCE_NAME: "postgresql://prometheus:prometheus_password@db:5432/fraiseql_prod?sslmode=disable"
  volumes:
    - ./postgres_exporter_queries.yml:/etc/postgres_exporter/queries.yml:ro
  command:
    - "--extend.query-path=/etc/postgres_exporter/queries.yml"
  ports:
    - "9187:9187"
```

The `prometheus` role is created by `init.sql` with `pg_monitor` access.

See `docs/observability/query-stats.md` for full documentation on
interpreting query performance data.

---

*Docker configurations are optimized for security, performance, and developer experience.*
