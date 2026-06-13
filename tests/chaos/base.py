"""Chaos Engineering Base Classes and Infrastructure

This module provides the foundation for chaos engineering tests in FraiseQL,
including metrics collection, test case management, and chaos injection utilities.
"""

import statistics
import time
import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChaosMetrics:
    """Metrics collected during a chaos test."""

    # Timing metrics
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None

    # Performance metrics
    query_times_ms: List[float] = field(default_factory=list)
    error_count: int = 0
    retry_count: int = 0

    # System metrics
    memory_usage_mb: List[float] = field(default_factory=list)
    cpu_usage_percent: List[float] = field(default_factory=list)

    # Chaos injection metrics
    chaos_injection_time: Optional[float] = None
    chaos_recovery_time: Optional[float] = None
    chaos_active_duration_ms: Optional[float] = None

    def start_test(self):
        """Mark the start of a chaos test."""
        self.start_time = time.time()

    def end_test(self):
        """Mark the end of a chaos test."""
        self.end_time = time.time()
        if self.start_time:
            self.duration_ms = (self.end_time - self.start_time) * 1000

    def record_query_time(self, duration_ms: float):
        """Record a query execution time."""
        self.query_times_ms.append(duration_ms)

    def record_error(self):
        """Record an error occurrence."""
        self.error_count += 1

    def record_retry(self):
        """Record a retry attempt."""
        self.retry_count += 1

    def start_chaos_injection(self):
        """Mark when chaos injection begins."""
        self.chaos_injection_time = time.time()

    def end_chaos_injection(self):
        """Mark when chaos injection ends."""
        recovery_time = time.time()
        if self.chaos_injection_time:
            self.chaos_recovery_time = recovery_time
            self.chaos_active_duration_ms = (recovery_time - self.chaos_injection_time) * 1000

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the chaos test metrics."""
        return {
            "duration_ms": self.duration_ms,
            "query_count": len(self.query_times_ms),
            "avg_query_time_ms": statistics.mean(self.query_times_ms)
            if self.query_times_ms
            else None,
            "p95_query_time_ms": statistics.quantiles(self.query_times_ms, n=20)[18]
            if len(self.query_times_ms) >= 20
            else None,
            "error_count": self.error_count,
            "retry_count": self.retry_count,
            "chaos_active_duration_ms": self.chaos_active_duration_ms,
        }


class ChaosTestCase(unittest.TestCase):
    """Base class for chaos engineering tests.

    Provides common functionality for chaos test setup, execution, and cleanup.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = ChaosMetrics()
        self.chaos_active = False
        self.baseline_file = "tests/chaos/baseline_metrics.json"
        # Pytest fixture support - allow pytest to inject fixtures
        self._pytest_fixtures = {}

    def setup_method(self, method=None):
        """Setup called before each test method."""
        self.metrics = ChaosMetrics()
        self.metrics.start_test()
        # Check if pytest has injected fixtures into self.__pytest_meta__
        if hasattr(self, "__pytest_meta__"):
            for name, value in self.__pytest_meta__.items():
                setattr(self, name, value)

    def teardown_method(self, method=None):
        """Teardown called after each test method."""
        self.metrics.end_test()
        self._save_results()

    def load_baseline(self, baseline_file: Optional[str] = None) -> Dict[str, Any]:
        """Load baseline metrics for comparison."""
        import json

        baseline_file = baseline_file or self.baseline_file

        try:
            with open(baseline_file) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def compare_to_baseline(self, operation: str) -> Dict[str, Any]:
        """Compare current metrics to baseline."""
        baseline = self.load_baseline()
        current = self.metrics.get_summary()

        if operation not in baseline:
            return {"error": f"No baseline found for operation: {operation}"}

        baseline_op = baseline[operation]

        # Calculate deviations
        result = {
            "operation": operation,
            "baseline": baseline_op,
            "current": current,
            "deviations": {},
        }

        # Compare key metrics
        for metric in ["avg_query_time_ms", "p95_query_time_ms", "error_count"]:
            if metric in baseline_op and metric in current:
                baseline_val = baseline_op[metric]
                current_val = current[metric]
                if baseline_val and current_val:
                    deviation = ((current_val - baseline_val) / baseline_val) * 100
                    result["deviations"][metric] = deviation

        return result

    def _save_results(self):
        """Save test results to file."""
        import json
        import os

        os.makedirs("tests/chaos/results", exist_ok=True)
        result_file = f"tests/chaos/results/{self.__class__.__name__}.json"

        results = {
            "test_class": self.__class__.__name__,
            "timestamp": time.time(),
            "metrics": self.metrics.get_summary(),
            "chaos_active": self.chaos_active,
        }

        with open(result_file, "w") as f:
            json.dump(results, f, indent=2)

    def inject_chaos(self, failure_type: str, duration: int, **kwargs):
        """Inject chaos into the system.

        This is a placeholder - actual implementation will be in subclasses
        or through decorators.
        """
        self.chaos_active = True
        self.metrics.start_chaos_injection()

        # Placeholder for chaos injection logic
        time.sleep(duration / 1000)  # Convert ms to seconds

        self.chaos_active = False
        self.metrics.end_chaos_injection()
