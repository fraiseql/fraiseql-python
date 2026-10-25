"""Tests for Grafana dashboard JSON structure and validity.

Tests verify:
- Dashboard JSON files are valid and parseable
- Required fields are present
- Panel structure is correct
- SQL queries are syntactically valid
- Variables are properly configured
"""

import json
import re
from pathlib import Path

import pytest

DASHBOARD_DIR = Path(__file__).parent.parent.parent / "grafana"
DASHBOARD_FILES = [
    "error_monitoring.json",
    "performance_metrics.json",
    "database_pool.json",
    "apq_effectiveness.json",
]

# The target field holding the query, per datasource plugin
DATASOURCE_QUERY_FIELD = {
    "grafana-postgresql-datasource": "rawSql",
    "prometheus": "expr",
}


@pytest.fixture
def dashboard_files() -> None:
    """Return list of dashboard file paths."""
    return [DASHBOARD_DIR / filename for filename in DASHBOARD_FILES]


@pytest.fixture
def dashboards(dashboard_files) -> None:
    """Load all dashboard JSON files."""
    dashboards = {}
    for filepath in dashboard_files:
        with filepath.open() as f:
            dashboards[filepath.stem] = json.load(f)
    return dashboards


class TestDashboardStructure:
    """Test dashboard JSON structure and validity."""

    def test_all_dashboard_files_exist(self, dashboard_files) -> None:
        """All expected dashboard files should exist."""
        for filepath in dashboard_files:
            assert filepath.exists(), f"Dashboard file not found: {filepath}"

    def test_dashboards_are_valid_json(self, dashboard_files) -> None:
        """All dashboard files should contain valid JSON."""
        for filepath in dashboard_files:
            with filepath.open() as f:
                try:
                    json.load(f)
                except json.JSONDecodeError as e:
                    pytest.fail(f"Invalid JSON in {filepath}: {e}")

    def test_dashboards_have_required_top_level_keys(self, dashboards) -> None:
        """Each dashboard should have required top-level keys."""
        required_keys = ["dashboard", "overwrite", "message"]

        for name, dashboard in dashboards.items():
            for key in required_keys:
                assert key in dashboard, f"{name}: Missing required key '{key}'"

    def test_dashboard_metadata(self, dashboards) -> None:
        """Each dashboard should have proper metadata."""
        required_metadata = ["title", "tags", "timezone", "schemaVersion", "panels"]

        for name, dashboard in dashboards.items():
            dashboard_obj = dashboard["dashboard"]
            for key in required_metadata:
                assert key in dashboard_obj, f"{name}: Missing metadata '{key}'"

            # Verify title is not empty
            assert dashboard_obj["title"], f"{name}: Title is empty"

            # Verify tags include 'fraiseql'
            assert "fraiseql" in dashboard_obj["tags"], f"{name}: Missing 'fraiseql' tag"

    def test_dashboard_has_panels(self, dashboards) -> None:
        """Each dashboard should have at least one panel."""
        for name, dashboard in dashboards.items():
            panels = dashboard["dashboard"]["panels"]
            assert len(panels) > 0, f"{name}: Dashboard has no panels"

    def test_panel_structure(self, dashboards) -> None:
        """Each panel should have required fields."""
        required_panel_fields = ["id", "title", "type", "gridPos", "targets"]

        for name, dashboard in dashboards.items():
            panels = dashboard["dashboard"]["panels"]

            for i, panel in enumerate(panels):
                for field in required_panel_fields:
                    assert field in panel, (
                        f"{name}, panel {i} ({panel.get('title', 'untitled')}): "
                        f"Missing field '{field}'"
                    )

                # Verify panel ID is unique
                panel_ids = [p["id"] for p in panels]
                assert len(panel_ids) == len(set(panel_ids)), f"{name}: Duplicate panel IDs found"

    def test_panel_grid_position(self, dashboards) -> None:
        """Each panel should have valid grid position."""
        for name, dashboard in dashboards.items():
            panels = dashboard["dashboard"]["panels"]

            for panel in panels:
                grid_pos = panel["gridPos"]

                # Check required grid position fields
                assert "h" in grid_pos, f"{name}, panel '{panel['title']}': Missing height"
                assert "w" in grid_pos, f"{name}, panel '{panel['title']}': Missing width"
                assert "x" in grid_pos, f"{name}, panel '{panel['title']}': Missing x position"
                assert "y" in grid_pos, f"{name}, panel '{panel['title']}': Missing y position"

                # Validate grid values
                assert 0 <= grid_pos["x"] <= 24, (
                    f"{name}, panel '{panel['title']}': Invalid x position {grid_pos['x']}"
                )
                assert 0 < grid_pos["w"] <= 24, (
                    f"{name}, panel '{panel['title']}': Invalid width {grid_pos['w']}"
                )
                assert grid_pos["h"] > 0, (
                    f"{name}, panel '{panel['title']}': Invalid height {grid_pos['h']}"
                )

    def test_panel_targets(self, dashboards) -> None:
        """Each panel should have targets with a SQL query or a PromQL expression."""
        for name, dashboard in dashboards.items():
            panels = dashboard["dashboard"]["panels"]

            for panel in panels:
                targets = panel["targets"]
                assert len(targets) > 0, f"{name}, panel '{panel['title']}': No targets defined"

                datasource_type = panel.get("datasource", {}).get("type")
                assert datasource_type in DATASOURCE_QUERY_FIELD, (
                    f"{name}, panel '{panel['title']}': Unknown datasource {datasource_type!r}"
                )
                query_field = DATASOURCE_QUERY_FIELD[datasource_type]

                for target in targets:
                    assert "refId" in target, (
                        f"{name}, panel '{panel['title']}': Target missing refId"
                    )
                    assert target.get(query_field), (
                        f"{name}, panel '{panel['title']}': Target missing {query_field}"
                    )

    def test_panel_datasources_are_dashboard_variables(self, dashboards) -> None:
        """Panels should read the dashboard's datasource variable."""
        for name, dashboard in dashboards.items():
            variables = {v["name"]: v for v in dashboard["dashboard"]["templating"]["list"]}
            assert variables.get("datasource", {}).get("type") == "datasource", (
                f"{name}: Missing 'datasource' template variable"
            )
            expected = {"type": variables["datasource"]["query"], "uid": "${datasource}"}

            for panel in dashboard["dashboard"]["panels"]:
                assert panel["datasource"] == expected, (
                    f"{name}, panel '{panel['title']}': datasource should be {expected}"
                )
                for target in panel["targets"]:
                    assert target.get("datasource", expected) == expected, (
                        f"{name}, panel '{panel['title']}': target datasource differs from panel"
                    )

    def test_templating_variables(self, dashboards) -> None:
        """Variables used by the queries should be defined by the dashboard."""
        for name, dashboard in dashboards.items():
            assert "templating" in dashboard["dashboard"], (
                f"{name}: Missing templating configuration"
            )

            templating = dashboard["dashboard"]["templating"]
            assert "list" in templating, f"{name}: Missing template variable list"

            variables = {v["name"]: v for v in templating["list"]}

            for panel in dashboard["dashboard"]["panels"]:
                for target in panel["targets"]:
                    query = target.get("rawSql") or target.get("expr", "")
                    # $__name are Grafana's own macros and variables
                    for used in re.findall(r"\$(?!__)(\w+)", query):
                        assert used in variables, (
                            f"{name}, panel '{panel['title']}': Undefined variable ${used}"
                        )

            # The error tables have an environment column; it should offer 'production'
            if "environment" in variables:
                env_options = [opt["value"] for opt in variables["environment"]["options"]]
                assert "production" in env_options, (
                    f"{name}: Environment variable missing 'production' option"
                )

    def test_time_configuration(self, dashboards) -> None:
        """Dashboards should have time configuration."""
        for name, dashboard in dashboards.items():
            assert "time" in dashboard["dashboard"], f"{name}: Missing time configuration"

            time_config = dashboard["dashboard"]["time"]
            assert "from" in time_config, f"{name}: Missing time 'from'"
            assert "to" in time_config, f"{name}: Missing time 'to'"

    def test_refresh_rate(self, dashboards) -> None:
        """Dashboards should have refresh rate configured."""
        for name, dashboard in dashboards.items():
            assert "refresh" in dashboard["dashboard"], f"{name}: Missing refresh configuration"

            refresh = dashboard["dashboard"]["refresh"]
            # Should be valid refresh interval (10s, 30s, 1m, etc.)
            assert refresh in [
                "10s",
                "30s",
                "1m",
                "5m",
                False,
            ], f"{name}: Invalid refresh rate '{refresh}'"


class TestDashboardSpecificContent:
    """Test dashboard-specific content requirements."""

    def test_error_monitoring_dashboard(self, dashboards) -> None:
        """Error monitoring dashboard should have error-specific panels."""
        dashboard = dashboards["error_monitoring"]
        panel_titles = [p["title"] for p in dashboard["dashboard"]["panels"]]

        # Check for expected panels
        expected_panels = [
            "Error Rate Over Time",
            "Top 10 Error Fingerprints",
            "Error Resolution Status",
        ]

        for expected in expected_panels:
            assert expected in panel_titles, f"Error monitoring dashboard missing panel: {expected}"

    def test_performance_metrics_dashboard(self, dashboards) -> None:
        """Performance metrics dashboard should have performance-specific panels."""
        dashboard = dashboards["performance_metrics"]
        panel_titles = [p["title"] for p in dashboard["dashboard"]["panels"]]

        expected_panels = [
            "Request Rate (req/sec)",
            "Response Time Percentiles",
            "Slowest Endpoints (P99)",
        ]

        for expected in expected_panels:
            assert expected in panel_titles, f"Performance dashboard missing panel: {expected}"

    def test_database_pool_dashboard(self, dashboards) -> None:
        """Database pool dashboard should have pool-specific panels."""
        dashboard = dashboards["database_pool"]
        panel_titles = [p["title"] for p in dashboard["dashboard"]["panels"]]

        expected_panels = [
            "Active Connections",
            "Idle in Transaction",
            "Connection Utilization",
            "Top Queries by Total Time",
        ]

        for expected in expected_panels:
            assert expected in panel_titles, f"Database pool dashboard missing panel: {expected}"

    def test_apq_effectiveness_dashboard(self, dashboards) -> None:
        """APQ dashboard should have APQ storage panels."""
        dashboard = dashboards["apq_effectiveness"]
        panel_titles = [p["title"] for p in dashboard["dashboard"]["panels"]]

        expected_panels = [
            "Stored Persisted Queries",
            "APQ Storage Growth",
            "Largest Persisted Queries",
        ]

        for expected in expected_panels:
            assert expected in panel_titles, (
                f"APQ effectiveness dashboard missing panel: {expected}"
            )


class TestDashboardTags:
    """Test dashboard tagging for organization."""

    def test_dashboards_have_appropriate_tags(self, dashboards) -> None:
        """Each dashboard should have relevant tags."""
        expected_tags = {
            "error_monitoring": ["fraiseql", "errors", "monitoring"],
            "performance_metrics": ["fraiseql", "performance", "prometheus"],
            "database_pool": ["fraiseql", "database", "pool", "connections"],
            "apq_effectiveness": ["fraiseql", "apq", "persisted-queries", "performance"],
        }

        for name, dashboard in dashboards.items():
            tags = dashboard["dashboard"]["tags"]
            expected = expected_tags[name]

            for tag in expected:
                assert tag in tags, f"{name}: Missing expected tag '{tag}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
