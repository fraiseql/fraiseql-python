# Observability Integration Example

🟠 ADVANCED | ⏱️ 25 min | 🎯 Monitoring | 🏷️ DevOps

A comprehensive example of integrating FraiseQL applications with modern observability tools including Loki for log aggregation, Grafana for visualization, and Prometheus metrics collection.

**What you'll learn:**

- Structured logging with Loki integration
- Application metrics and monitoring setup
- Grafana dashboard configuration
- Observability best practices for GraphQL APIs
- Log aggregation and analysis patterns

**Prerequisites:**

- `../blog_simple/` - Basic GraphQL API patterns
- Docker and Docker Compose knowledge
- Understanding of monitoring concepts

**Next steps:**

- `../saas-starter/` - A multi-tenant production app

## Overview

This example demonstrates how to add comprehensive observability to FraiseQL applications using industry-standard tools. It includes:

- **Loki**: Log aggregation and analysis
- **Grafana**: Visualization and dashboards
- **Prometheus**: Metrics collection (via application integration)
- **Structured logging**: Consistent log formats for better analysis

### Architecture

```
FraiseQL App → Structured Logs → Loki → Grafana Dashboards
              → Metrics → Prometheus → Grafana Panels
              → Health Checks → Monitoring Alerts
```

## Components

### 1. Loki Configuration

**Purpose**: Centralized log aggregation and analysis

**Files**:

- `loki/loki-config.yaml` - Loki server configuration
- `loki/promtail-config.yaml` - Log shipping configuration
- `loki/grafana-datasources.yaml` - Grafana data source setup

**Key Features**:

- Structured JSON logging support
- Label-based log filtering
- Long-term log retention
- Query language for log analysis

### 2. Grafana Dashboards

**Purpose**: Visualization and monitoring dashboards

**Files**:

- `loki/grafana-datasources.yaml` - Data source definitions

**Capabilities**:

- Log visualization with Loki
- Metrics panels with Prometheus
- Alerting and notification setup
- Custom dashboard creation

### 3. Docker Compose Setup

**Purpose**: Complete observability stack orchestration

**File**: `docker-compose.loki.yml`

**Services**:

- Loki (log aggregation)
- Grafana (visualization)
- Promtail (log shipping)
- Optional: Prometheus (metrics)

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- Python 3.13+ (for FraiseQL app)
- PostgreSQL (for application data)

### 2. Start Observability Stack

```bash
# Start Loki, Grafana, and Promtail
docker-compose -f docker-compose.loki.yml up -d

# Verify services are running
docker-compose -f docker-compose.loki.yml ps
```

### 3. Access Interfaces

- **Grafana**: http://localhost:3000 (admin/admin)
- **Loki**: http://localhost:3100 (API endpoint)
- **Promtail**: Runs as agent, no direct access

### 4. Configure Grafana

```bash
# Import data sources (automated via grafana-datasources.yaml)
curl -X POST -H "Content-Type: application/json" \
  -d @loki/grafana-datasources.yaml \
  http://admin:admin@localhost:3000/api/datasources
```

## Application Integration

### Structured Logging Setup

```python
import logging
import json
from datetime import datetime

# Configure structured logging
class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, 'user_id'):
            log_entry["user_id"] = record.user_id
        if hasattr(record, 'request_id'):
            log_entry["request_id"] = record.request_id
        if hasattr(record, 'query'):
            log_entry["query"] = record.query

        return json.dumps(log_entry)

# Configure logger
logger = logging.getLogger("fraiseql.app")
handler = logging.StreamHandler()
handler.setFormatter(StructuredFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)
```

### GraphQL Operation Logging

```python
@fraiseql.query
async def get_user(info, id: UUID) -> User | None:
    """Get user with observability logging."""
    request_id = info.context.get("request_id", "unknown")

    logger.info(
        "Executing get_user query",
        extra={
            "request_id": request_id,
            "user_id": str(id),
            "operation": "get_user"
        }
    )

    try:
        # Your database logic here
        user = await db.find_one("v_users", id=id)

        if user:
            logger.info(
                "User found",
                extra={"request_id": request_id, "user_id": str(id)}
            )
        else:
            logger.warning(
                "User not found",
                extra={"request_id": request_id, "user_id": str(id)}
            )

        return user

    except Exception as e:
        logger.error(
            "Error fetching user",
            extra={
                "request_id": request_id,
                "user_id": str(id),
                "error": str(e)
            },
            exc_info=True
        )
        raise
```

### Metrics Collection

```python
from prometheus_client import Counter, Histogram, Gauge
import time

# Define metrics
GRAPHQL_REQUESTS = Counter(
    'graphql_requests_total',
    'Total GraphQL requests',
    ['operation', 'status']
)

GRAPHQL_DURATION = Histogram(
    'graphql_request_duration_seconds',
    'GraphQL request duration',
    ['operation']
)

ACTIVE_CONNECTIONS = Gauge(
    'db_connections_active',
    'Number of active database connections'
)

@fraiseql.query
async def list_posts(info, limit: int = 10) -> list[Post]:
    """List posts with metrics collection."""
    start_time = time.time()

    try:
        posts = await db.find("v_posts", limit=limit)

        # Record metrics
        GRAPHQL_REQUESTS.labels(
            operation="list_posts",
            status="success"
        ).inc()

        GRAPHQL_DURATION.labels(
            operation="list_posts"
        ).observe(time.time() - start_time)

        return posts

    except Exception as e:
        GRAPHQL_REQUESTS.labels(
            operation="list_posts",
            status="error"
        ).inc()

        raise
```

## Loki Log Queries

### Basic Queries

```logql
# All application logs
{app="fraiseql"}

# Error logs only
{app="fraiseql", level="ERROR"}

# User-specific operations
{app="fraiseql"} |= "user_id"
```

### Advanced Queries

```logql
# GraphQL operations by user
{app="fraiseql"} |= "operation" | logfmt | operation != "" | user_id != ""

# Error rate analysis
rate({app="fraiseql", level="ERROR"}[5m])

# Slow queries (>1 second)
{app="fraiseql"} |= "duration" | logfmt | duration > 1.0
```

## Grafana Dashboard Setup

### 1. Create Dashboard

```json
{
  "dashboard": {
    "title": "FraiseQL Observability",
    "tags": ["fraiseql", "graphql", "observability"],
    "panels": [
      {
        "title": "GraphQL Request Rate",
        "type": "graph",
        "targets": [{
          "expr": "rate(graphql_requests_total[5m])",
          "legendFormat": "{{operation}}"
        }]
      },
      {
        "title": "Error Logs",
        "type": "logs",
        "targets": [{
          "expr": "{app=\"fraiseql\", level=\"ERROR\"}"
        }]
      }
    ]
  }
}
```

### 2. Import Dashboard

```bash
# Via Grafana UI: Dashboard -> Import
# Or via API
curl -X POST -H "Content-Type: application/json" \
  -d @dashboard.json \
  http://admin:admin@localhost:3000/api/dashboards/import
```

## Monitoring Best Practices

### 1. Log Levels

- **DEBUG**: Detailed diagnostic information
- **INFO**: General operational messages
- **WARNING**: Warning conditions that don't stop operation
- **ERROR**: Error conditions that need attention
- **CRITICAL**: Critical errors requiring immediate action

### 2. Structured Logging Fields

Always include:

- `timestamp`: ISO 8601 UTC format
- `level`: Log level
- `logger`: Logger name
- `message`: Human-readable message
- `request_id`: Request correlation ID
- `user_id`: User identifier (when applicable)
- `operation`: GraphQL operation name

### 3. Metrics to Monitor

**Application Metrics**:

- Request rate per operation
- Error rate per operation
- Response time percentiles
- Active connections

**Business Metrics**:

- User registration rate
- Query complexity distribution
- Cache hit rates

### 4. Alerting Rules

```yaml
# Prometheus alerting rules
groups:
  - name: fraiseql
    rules:
      - alert: HighErrorRate
        expr: rate(graphql_requests_total{status="error"}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High GraphQL error rate detected"

      - alert: SlowQueries
        expr: histogram_quantile(0.95, rate(graphql_request_duration_seconds[5m])) > 2.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow GraphQL queries detected"
```

## Production Deployment

### 1. Loki Configuration

```yaml
# Production loki-config.yaml
server:
  http_listen_port: 3100
  grpc_listen_port: 9096

storage_config:
  filesystem:
    directory: /loki/chunks

limits_config:
  retention_period: 30d
  max_query_length: 721h

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h
```

### 2. Promtail Configuration

```yaml
# Production promtail-config.yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: fraiseql
    static_configs:
      - targets:
          - localhost
        labels:
          job: fraiseql
          app: fraiseql
          env: production
    pipeline_stages:
      - json:
          expressions:
            level: level
            message: message
      - labels:
          level:
          app:
```

### 3. Scaling Considerations

- **Loki**: Use object storage (S3, GCS) for long-term retention
- **Grafana**: Configure external database for dashboard persistence
- **Prometheus**: Use federation for multi-region setups
- **Promtail**: Deploy as DaemonSet in Kubernetes

## Troubleshooting

### Common Issues

**Loki not receiving logs**:

```bash
# Check Promtail status
docker-compose -f docker-compose.loki.yml logs promtail

# Verify Loki is accessible
curl http://localhost:3100/ready
```

**Grafana data source errors**:

```bash
# Test Loki connection
curl "http://localhost:3100/loki/api/v1/query?query={app=\"fraiseql\"}"
```

**Metrics not appearing**:

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets
```

## Next Steps

After implementing observability:

1. **Add distributed tracing** (Jaeger, Zipkin)
2. **Implement log-based alerting** (ElastAlert, Loki alerts)
3. **Create custom Grafana panels** for business metrics
4. **Set up log archiving** for compliance requirements
5. **Implement anomaly detection** using metrics data

---

**FraiseQL Observability Integration**. Demonstrates comprehensive monitoring, logging, and visualization setup for production GraphQL applications.

## Support

- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)
- **Discord**: [FraiseQL Community](https://discord.gg/fraiseql)
- **Documentation**: [FraiseQL Docs](../../docs)
