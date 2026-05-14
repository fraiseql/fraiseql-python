"""FraiseQL monitoring module.

Provides utilities for application monitoring including:
- Prometheus metrics integration
- Health check patterns
- Pre-built health checks for common services
- OpenTelemetry tracing
- PostgreSQL-native error tracking (Sentry replacement)
- Extensible notification system (Email, Slack, Webhook)

Example:
    >>> from fraiseql.monitoring import HealthCheck, check_database, check_pool_stats
    >>> from fraiseql.monitoring import setup_metrics, MetricsConfig
    >>> from fraiseql.monitoring import init_error_tracker, get_error_tracker
    >>>
    >>> # Set up metrics
    >>> setup_metrics(MetricsConfig(enabled=True))
    >>>
    >>> # Initialize error tracking
    >>> tracker = init_error_tracker(db_pool, environment="production")
    >>>
    >>> # Capture errors
    >>> try:
    >>>     risky_operation()
    >>> except Exception as e:
    >>>     await tracker.capture_exception(e, context={"request": request_data})
    >>>
    >>> # Create health checks with pre-built functions
    >>> health = HealthCheck()
    >>> health.add_check("database", check_database)
    >>> health.add_check("pool", check_pool_stats)
    >>>
    >>> # Run checks
    >>> result = await health.run_checks()
"""

from .apq_metrics import (
    APQMetrics,
    APQMetricsSnapshot,
    get_global_metrics,
    reset_global_metrics,
)
from .health import (
    CheckFunction,
    CheckResult,
    HealthCheck,
    HealthStatus,
)
from .health_checks import (
    check_database,
    check_pool_stats,
    check_query_stats,
)
from .metrics import (
    FraiseQLMetrics,
    MetricsConfig,
    MetricsMiddleware,
    get_metrics,
    setup_metrics,
    with_metrics,
)
from .notifications import (
    EmailChannel,
    NotificationManager,
    SlackChannel,
    WebhookChannel,
)
from .postgres_error_tracker import (
    PostgreSQLErrorTracker,
    get_error_tracker,
    init_error_tracker,
)
from .query_stats import (
    QueryStatsCollector,
    QueryStatsSnapshot,
    get_query_stats_collector,
    init_query_stats,
)

__all__ = [
    "APQMetrics",
    "APQMetricsSnapshot",
    "CheckFunction",
    "CheckResult",
    "EmailChannel",
    "FraiseQLMetrics",
    "HealthCheck",
    "HealthStatus",
    "MetricsConfig",
    "MetricsMiddleware",
    "NotificationManager",
    "PostgreSQLErrorTracker",
    "QueryStatsCollector",
    "QueryStatsSnapshot",
    "SlackChannel",
    "WebhookChannel",
    "check_database",
    "check_pool_stats",
    "check_query_stats",
    "get_error_tracker",
    "get_global_metrics",
    "get_metrics",
    "get_query_stats_collector",
    "init_error_tracker",
    "init_query_stats",
    "reset_global_metrics",
    "setup_metrics",
    "with_metrics",
]
