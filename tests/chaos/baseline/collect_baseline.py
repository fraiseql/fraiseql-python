#!/usr/bin/env python3
"""Chaos Engineering Baseline Metrics Collector

This script collects baseline performance metrics for FraiseQL operations
to establish statistical baselines for chaos engineering tests.

Run this script to generate baseline_metrics.json with confidence intervals.
"""

import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List


class BaselineCollector:
    """Collects baseline performance metrics."""

    def __init__(self, samples: int = 10):
        self.samples = samples
        self.baseline_file = Path("tests/chaos/baseline_metrics.json")

    def collect_baselines(self) -> Dict[str, Any]:
        """Collect baseline metrics for all operations."""
        print("🔬 Collecting Baseline Metrics for Chaos Engineering")
        print(f"📊 Running {self.samples} samples per operation")
        print("=" * 60)

        baselines = {}

        # Simple GraphQL query
        baselines["simple_query"] = self._collect_operation_baseline(
            "Simple GraphQL Query", self._measure_simple_query
        )

        # Complex nested query
        baselines["complex_query"] = self._collect_operation_baseline(
            "Complex Nested Query", self._measure_complex_query
        )

        # Database connection
        baselines["db_connection"] = self._collect_operation_baseline(
            "Database Connection", self._measure_db_connection
        )

        # Authentication
        baselines["authentication"] = self._collect_operation_baseline(
            "JWT Authentication", self._measure_authentication
        )

        # Cache operation
        baselines["cache_operation"] = self._collect_operation_baseline(
            "Cache Read/Write", self._measure_cache_operation
        )

        # Save baselines
        self._save_baselines(baselines)

        print("\n✅ Baseline collection complete!")
        print(f"📁 Results saved to: {self.baseline_file}")

        return baselines

    def _collect_operation_baseline(self, operation_name: str, measure_func) -> Dict[str, Any]:
        """Collect baseline metrics for a single operation."""
        print(f"\n🔍 Measuring: {operation_name}")

        measurements = []

        for i in range(self.samples):
            try:
                duration_ms = measure_func()
                measurements.append(duration_ms)
                print(".1f")
            except Exception as e:
                print(f"❌ Sample {i + 1} failed: {e}")
                measurements.append(float("inf"))  # Mark as failed

        # Calculate statistics
        valid_measurements = [m for m in measurements if m != float("inf")]

        if not valid_measurements:
            print(f"⚠️  No valid measurements for {operation_name}")
            return {"error": "No valid measurements"}

        result = {
            "operation": operation_name,
            "samples": len(valid_measurements),
            "measurements_ms": valid_measurements,
            "mean_ms": statistics.mean(valid_measurements),
            "median_ms": statistics.median(valid_measurements),
            "stddev_ms": statistics.stdev(valid_measurements) if len(valid_measurements) > 1 else 0,
            "min_ms": min(valid_measurements),
            "max_ms": max(valid_measurements),
            "p95_ms": self._percentile(valid_measurements, 95),
            "p99_ms": self._percentile(valid_measurements, 99),
            "success_rate": len(valid_measurements) / self.samples,
        }

        print(
            f"📈 Mean: {result['mean_ms']:.2f}ms | StdDev: {result['stddev_ms']:.2f}ms | P95: {result['p95_ms']:.2f}ms"
        )

        return result

    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile from data."""
        if not data:
            return 0.0

        data_sorted = sorted(data)
        k = (len(data_sorted) - 1) * (percentile / 100.0)
        f = int(k)
        c = k - f

        if f + 1 < len(data_sorted):
            return data_sorted[f] + c * (data_sorted[f + 1] - data_sorted[f])
        return data_sorted[f]

    def _measure_simple_query(self) -> float:
        """Measure a simple GraphQL query."""
        # TODO: Implement actual FraiseQL query measurement
        # For now, simulate with a small delay
        start = time.time()
        time.sleep(0.015)  # Simulate 15ms query
        return (time.time() - start) * 1000

    def _measure_complex_query(self) -> float:
        """Measure a complex nested GraphQL query."""
        # TODO: Implement actual complex query measurement
        start = time.time()
        time.sleep(0.045)  # Simulate 45ms complex query
        return (time.time() - start) * 1000

    def _measure_db_connection(self) -> float:
        """Measure database connection time."""
        # TODO: Implement actual DB connection measurement
        start = time.time()
        time.sleep(0.005)  # Simulate 5ms connection
        return (time.time() - start) * 1000

    def _measure_authentication(self) -> float:
        """Measure authentication time."""
        # TODO: Implement actual JWT authentication measurement
        start = time.time()
        time.sleep(0.002)  # Simulate 2ms auth
        return (time.time() - start) * 1000

    def _measure_cache_operation(self) -> float:
        """Measure cache read/write time."""
        # TODO: Implement actual cache operation measurement
        start = time.time()
        time.sleep(0.001)  # Simulate 1ms cache operation
        return (time.time() - start) * 1000

    def _save_baselines(self, baselines: Dict[str, Any]):
        """Save baselines to JSON file."""
        self.baseline_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.baseline_file, "w") as f:
            json.dump(baselines, f, indent=2)

    def validate_baselines(self, baselines: Dict[str, Any]) -> bool:
        """Validate that baselines meet quality standards."""
        issues = []

        for operation, data in baselines.items():
            if "error" in data:
                issues.append(f"{operation}: {data['error']}")
                continue

            # Check sample count
            if data["samples"] < self.samples * 0.8:  # 80% success rate
                issues.append(
                    f"{operation}: Only {data['samples']}/{self.samples} successful samples"
                )

            # Check variance (stddev should be reasonable)
            mean = data["mean_ms"]
            stddev = data["stddev_ms"]
            if mean > 0 and (stddev / mean) > 0.5:  # More than 50% variance
                issues.append(f"{operation}: High variance (stddev/mean = {stddev / mean:.2f})")

        if issues:
            print("⚠️  Baseline quality issues:")
            for issue in issues:
                print(f"   - {issue}")
            return False

        print("✅ Baseline quality validated")
        return True


def main():
    """Main entry point."""
    collector = BaselineCollector(samples=15)  # 15 samples for better statistics

    try:
        baselines = collector.collect_baselines()

        if collector.validate_baselines(baselines):
            print("\n🎉 Baselines ready for chaos engineering!")
            return 0
        print("\n⚠️  Baselines collected but quality issues detected")
        return 1

    except Exception as e:
        print(f"\n❌ Baseline collection failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
