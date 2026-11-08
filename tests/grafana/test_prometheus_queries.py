"""The PromQL of the dashboards uses only metrics and labels FraiseQL exports.

The series are the ones GET /metrics serves once MetricsMiddleware has recorded a
request (setup_metrics); job and instance are added by Prometheus when it scrapes.
"""

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("prometheus_client")

from prometheus_client.parser import text_string_to_metric_families

from fraiseql.monitoring.metrics.collectors import FraiseQLMetrics

DASHBOARD_DIR = Path(__file__).parent.parent.parent / "grafana"
SCRAPE_LABELS = {"job", "instance"}


@pytest.fixture(scope="module")
def exported_series() -> dict[str, set[str]]:
    """Exported series name -> label names, after the middleware recorded a request."""
    metrics = FraiseQLMetrics()
    metrics.http_requests_total.labels(method="POST", endpoint="/graphql", status=200).inc()
    metrics.http_request_duration.labels(method="POST", endpoint="/graphql").observe(0.1)
    metrics.record_response_time(100)
    metrics.record_error("ValueError", "HTTP_ERROR", "POST /graphql")

    series: dict[str, set[str]] = {}
    for family in text_string_to_metric_families(metrics.generate_metrics().decode()):
        for sample in family.samples:
            series.setdefault(sample.name, set()).update(sample.labels)
    return series


def _prometheus_queries() -> list:
    params = []
    for path in sorted(DASHBOARD_DIR.glob("*.json")):
        dashboard = json.loads(path.read_text())["dashboard"]
        for variable in dashboard["templating"]["list"]:
            if variable.get("definition"):
                params.append(
                    pytest.param(variable["definition"], id=f"{path.stem}/${variable['name']}")
                )
        for panel in dashboard["panels"]:
            for target in panel["targets"]:
                if "expr" in target:
                    params.append(
                        pytest.param(
                            target["expr"], id=f"{path.stem}/{panel['title']}/{target['refId']}"
                        )
                    )
    return params


@pytest.mark.parametrize("expr", _prometheus_queries())
def test_expression_uses_exported_metrics(expr, exported_series) -> None:
    """Each fraiseql_* metric exists, with every label the expression selects or groups by."""
    metric_names = set(re.findall(r"\bfraiseql_\w+", expr))
    assert metric_names, f"No FraiseQL metric in {expr}"

    labels = set()
    for selector in re.findall(r"\{([^}]*)\}", expr):
        labels |= set(re.findall(r"(\w+)\s*!?=~?", selector))
    for grouping in re.findall(r"\bby\s*\(([^)]*)\)", expr):
        labels |= {label.strip() for label in grouping.split(",")}
    labels |= {label for _, label in re.findall(r"label_values\((\w+),\s*(\w+)\)", expr)}

    for name in metric_names:
        assert name in exported_series, f"{name} is not exported"
        missing = labels - exported_series[name] - SCRAPE_LABELS
        assert not missing, f"{name} has no label {sorted(missing)}"
