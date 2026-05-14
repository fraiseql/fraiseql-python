"""Validate postgres_exporter custom queries YAML structure."""

from pathlib import Path

import yaml

QUERIES_PATH = Path("deploy/docker/postgres_exporter_queries.yml")

VALID_USAGES = {"COUNTER", "GAUGE", "LABEL", "HISTOGRAM"}


class TestPostgresExporterQueries:
    """Validate the YAML matches postgres_exporter's expected format."""

    def test_file_exists(self) -> None:
        assert QUERIES_PATH.exists(), f"{QUERIES_PATH} not found"

    def test_valid_yaml(self) -> None:
        data = yaml.safe_load(QUERIES_PATH.read_text())
        assert isinstance(data, dict)

    def test_each_query_has_required_fields(self) -> None:
        data = yaml.safe_load(QUERIES_PATH.read_text())
        for name, config in data.items():
            assert "query" in config, f"{name}: missing 'query' field"
            assert "metrics" in config, f"{name}: missing 'metrics' field"
            assert isinstance(config["metrics"], list), (
                f"{name}: 'metrics' must be a list"
            )

    def test_metrics_have_usage_and_description(self) -> None:
        data = yaml.safe_load(QUERIES_PATH.read_text())
        for name, config in data.items():
            for metric in config["metrics"]:
                assert isinstance(metric, dict), (
                    f"{name}: each metric must be a dict"
                )
                for metric_name, metric_config in metric.items():
                    assert "usage" in metric_config, (
                        f"{name}.{metric_name}: missing 'usage'"
                    )
                    assert metric_config["usage"] in VALID_USAGES, (
                        f"{name}.{metric_name}: invalid usage "
                        f"'{metric_config['usage']}'"
                    )
                    assert "description" in metric_config, (
                        f"{name}.{metric_name}: missing 'description'"
                    )

    def test_queries_reference_v_query_stats(self) -> None:
        data = yaml.safe_load(QUERIES_PATH.read_text())
        for name, config in data.items():
            assert "v_query_stats" in config["query"], (
                f"{name}: query should reference v_query_stats view"
            )

    def test_metric_naming_follows_prometheus_conventions(self) -> None:
        """Metric names in the YAML keys should use snake_case."""
        data = yaml.safe_load(QUERIES_PATH.read_text())
        for name in data:
            assert name.startswith("fraiseql_pg_"), (
                f"Query group '{name}' should start with 'fraiseql_pg_'"
            )
            assert name == name.lower(), (
                f"Query group '{name}' should be lowercase"
            )

    def test_expected_query_groups_present(self) -> None:
        data = yaml.safe_load(QUERIES_PATH.read_text())
        assert "fraiseql_pg_query_stats" in data
        assert "fraiseql_pg_database_cache_hit" in data
