"""Phase 1 Chaos Engineering Success Criteria

This module implements validation logic for Phase 1 chaos engineering test success criteria.
Tests validate that FraiseQL maintains acceptable performance and reliability under network chaos.
"""

import statistics
from typing import Any, Dict, List, Tuple

from chaos.base import ChaosTestCase


class Phase1SuccessCriteria:
    """Success criteria validation for Phase 1 chaos tests."""

    # Performance thresholds (from chaos engineering plan)
    MAX_LATENCY_DEGRADATION = 5.0  # seconds (5000ms)
    MIN_SUCCESS_RATE = 0.80  # 80% operations must succeed
    MAX_ERROR_RATE_SPIKE = 0.50  # Error rate can increase by max 50% under chaos
    RECOVERY_TIME_MAX = 2.0  # seconds to recover to baseline

    # Network-specific thresholds
    LATENCY_TEST_MAX_DEGRADATION = 3.0  # seconds for latency tests
    PACKET_LOSS_MAX_SUCCESS_DROP = 0.30  # Max 30% success rate drop under packet loss

    @classmethod
    def validate_connection_chaos_test(
        cls, test_case: ChaosTestCase, baseline_metrics: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate database connection chaos test results.

        Success Criteria:
        - System continues to operate during connection failures
        - Recovery is automatic and within acceptable time
        - Connection pool handles exhaustion gracefully
        """
        results = test_case.metrics.get_summary()
        comparison = test_case.compare_to_baseline("db_connection")

        issues = []
        passed = True

        # Check that some operations succeeded under chaos
        if results.get("error_count", 0) > results.get("query_count", 1) * 0.9:
            issues.append("Too many failures under connection chaos")
            passed = False

        # Check recovery time (if applicable)
        if "current" in comparison and "baseline" in comparison:
            current_time = comparison["current"].get("avg_query_time_ms", 0)
            baseline_time = comparison["baseline"].get("mean_ms", 0)

            if current_time > baseline_time * 2:
                issues.append(
                    f"Recovery time degradation too high: {current_time:.1f}ms (baseline: {baseline_time:.1f}ms)"
                )
                passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": "connection_chaos",
            "total_operations": results.get("query_count", 0),
            "errors": results.get("error_count", 0),
            "success_rate": 1
            - (results.get("error_count", 0) / max(results.get("query_count", 1), 1)),
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_latency_chaos_test(
        cls, test_case: ChaosTestCase, latency_ms: int
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate network latency chaos test results.

        Success Criteria:
        - Performance degrades proportionally to latency
        - No catastrophic failures under high latency
        - System remains responsive within limits
        """
        results = test_case.metrics.get_summary()
        comparison = test_case.compare_to_baseline("db_connection")

        issues = []
        passed = True

        # Check that operations still complete (with timeout)
        total_ops = results.get("query_count", 0)
        if total_ops == 0:
            issues.append("No operations completed under latency chaos")
            passed = False

        # Check latency impact is reasonable
        expected_min_time = latency_ms + 10  # Base time + network latency
        avg_time = results.get("avg_query_time_ms", 0)

        if avg_time > 0:
            if avg_time < expected_min_time * 0.5:
                issues.append(
                    f"Latency impact too low: {avg_time:.1f}ms (expected >{expected_min_time * 0.5:.1f}ms)"
                )
            elif avg_time > expected_min_time * 3:
                issues.append(
                    f"Latency impact too high: {avg_time:.1f}ms (expected <{expected_min_time * 3:.1f}ms)"
                )

        # Check error rate is acceptable
        error_rate = results.get("error_count", 0) / max(total_ops, 1)
        if error_rate > 0.2:  # Max 20% errors under latency
            issues.append(
                f"Error rate too high under latency: {error_rate:.1%} (max 20%)"
            )
            passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": "latency_chaos",
            "latency_injected_ms": latency_ms,
            "total_operations": total_ops,
            "avg_response_time_ms": avg_time,
            "error_rate": error_rate,
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_packet_loss_chaos_test(
        cls, test_case: ChaosTestCase, loss_rate: float
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate packet loss chaos test results.

        Success Criteria:
        - System handles packet loss with retries
        - Success rate degrades gracefully with loss rate
        - Recovery mechanisms work effectively
        """
        results = test_case.metrics.get_summary()

        issues = []
        passed = True

        total_ops = results.get("query_count", 0)
        errors = results.get("error_count", 0)
        success_rate = 1 - (errors / max(total_ops, 1))

        # Expected success rate accounting for loss and retries
        expected_min_success = max(0.5, 1.0 - loss_rate - 0.2)  # Loss + 20% retry factor

        if success_rate < expected_min_success:
            issues.append(
                f"Success rate too low: {success_rate:.2%} (expected >{expected_min_success:.2%})"
            )
            passed = False

        # Check retry behavior
        retries = results.get("retry_count", 0)
        if retries == 0 and loss_rate > 0.01:
            issues.append("No retries attempted under packet loss")
            passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": "packet_loss_chaos",
            "packet_loss_rate": loss_rate,
            "total_operations": total_ops,
            "success_rate": success_rate,
            "expected_min_success": expected_min_success,
            "retries_attempted": retries,
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_phase1_overall_success(
        cls, test_results: List[Tuple[bool, str, Dict[str, Any]]]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate overall Phase 1 success based on all test results.

        Success Criteria:
        - 80% of tests must pass
        - No critical failures in core functionality
        - Performance degradation within acceptable limits
        """
        if not test_results:
            return False, "FAIL", {"issues": ["No test results provided"]}

        total_tests = len(test_results)
        passed_tests = sum(1 for passed, _, _ in test_results if passed)
        pass_rate = passed_tests / total_tests

        issues = []

        # Check overall pass rate
        if pass_rate < cls.MIN_SUCCESS_RATE:
            issues.append(".1f")
            overall_pass = False
        else:
            overall_pass = True

        # Check for critical test failures
        critical_failures = 0
        for passed, _, details in test_results:
            test_type = details.get("test_type", "")
            if not passed and test_type in ["connection_chaos"]:
                critical_failures += 1

        if critical_failures > 0:
            issues.append(f"Critical test failures: {critical_failures}")
            overall_pass = False

        # Aggregate performance metrics
        all_response_times = []
        all_error_rates = []

        for _, _, details in test_results:
            if "avg_response_time_ms" in details and details["avg_response_time_ms"] > 0:
                all_response_times.append(details["avg_response_time_ms"])
            if "error_rate" in details:
                all_error_rates.append(details["error_rate"])

        avg_response_time = statistics.mean(all_response_times) if all_response_times else 0
        avg_error_rate = statistics.mean(all_error_rates) if all_error_rates else 0

        status_msg = "PASS" if overall_pass else "FAIL"
        summary = {
            "phase": "phase1_network_chaos",
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "pass_rate": pass_rate,
            "critical_failures": critical_failures,
            "avg_response_time_ms": avg_response_time,
            "avg_error_rate": avg_error_rate,
            "issues": issues,
            "recommendations": cls._generate_recommendations(test_results, pass_rate),
        }

        return overall_pass, status_msg, summary

    @classmethod
    def _generate_recommendations(
        cls, test_results: List[Tuple[bool, str, Dict[str, Any]]], pass_rate: float
    ) -> List[str]:
        """Generate recommendations based on test results."""
        recommendations = []

        if pass_rate < 0.8:
            recommendations.append(
                "Improve resilience to network chaos - consider adding more robust retry logic"
            )

        # Check latency handling
        latency_issues = sum(
            1
            for _, _, details in test_results
            if details.get("test_type") == "latency_chaos" and details.get("error_rate", 0) > 0.15
        )
        if latency_issues > 0:
            recommendations.append("Optimize handling of high network latency scenarios")

        # Check packet loss recovery
        loss_issues = sum(
            1
            for _, _, details in test_results
            if details.get("test_type") == "packet_loss_chaos"
            and details.get("success_rate", 1.0) < 0.7
        )
        if loss_issues > 0:
            recommendations.append("Enhance packet loss recovery mechanisms")

        # Check connection handling
        conn_issues = sum(
            1
            for _, _, details in test_results
            if details.get("test_type") == "connection_chaos" and details.get("error_rate", 0) > 0.3
        )
        if conn_issues > 0:
            recommendations.append("Strengthen database connection failure handling")

        if not recommendations:
            recommendations.append("Phase 1 chaos resilience is excellent - proceed to Phase 2")

        return recommendations


# Convenience functions for test validation


def validate_chaos_test_success(
    test_case: ChaosTestCase, test_type: str, baseline_metrics: Dict[str, Any], **kwargs
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a chaos test based on its type and success criteria.

    Args:
        test_case: The ChaosTestCase that was executed
        test_type: Type of test ("connection_chaos", "latency_chaos", "packet_loss_chaos")
        baseline_metrics: Baseline performance metrics
        **kwargs: Additional parameters (latency_ms, loss_rate, etc.)

    Returns:
        (passed, status_message, detailed_results)
    """
    if test_type == "connection_chaos":
        return Phase1SuccessCriteria.validate_connection_chaos_test(test_case, baseline_metrics)
    if test_type == "latency_chaos":
        latency_ms = kwargs.get("latency_ms", 500)
        return Phase1SuccessCriteria.validate_latency_chaos_test(test_case, latency_ms)
    if test_type == "packet_loss_chaos":
        loss_rate = kwargs.get("loss_rate", 0.05)
        return Phase1SuccessCriteria.validate_packet_loss_chaos_test(test_case, loss_rate)
    return False, "FAIL", {"issues": [f"Unknown test type: {test_type}"]}


# Phase 1 summary statistics


class Phase1Statistics:
    """Statistics and reporting for Phase 1 chaos tests."""

    @staticmethod
    def generate_phase_report(
        test_results: List[Tuple[bool, str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Generate a comprehensive Phase 1 report."""
        overall_passed, status, summary = Phase1SuccessCriteria.validate_phase1_overall_success(
            test_results
        )

        report = {
            "phase": "Phase 1: Network & Connectivity Chaos",
            "status": status,
            "overall_passed": overall_passed,
            "summary": summary,
            "test_breakdown": {},
            "performance_analysis": {},
            "recommendations": summary.get("recommendations", []),
        }

        # Breakdown by test type
        test_types = {}
        for passed, _, details in test_results:
            test_type = details.get("test_type", "unknown")
            if test_type not in test_types:
                test_types[test_type] = {"total": 0, "passed": 0}
            test_types[test_type]["total"] += 1
            if passed:
                test_types[test_type]["passed"] += 1

        report["test_breakdown"] = test_types

        # Performance analysis
        response_times = []
        error_rates = []

        for _, _, details in test_results:
            if "avg_response_time_ms" in details and details["avg_response_time_ms"] > 0:
                response_times.append(details["avg_response_time_ms"])
            if "error_rate" in details:
                error_rates.append(details["error_rate"])

        report["performance_analysis"] = {
            "avg_response_time_ms": statistics.mean(response_times) if response_times else 0,
            "median_response_time_ms": statistics.median(response_times) if response_times else 0,
            "max_response_time_ms": max(response_times) if response_times else 0,
            "avg_error_rate": statistics.mean(error_rates) if error_rates else 0,
            "response_time_variance": statistics.stdev(response_times)
            if len(response_times) > 1
            else 0,
        }

        return report

    @staticmethod
    def print_report(report: Dict[str, Any]):
        """Print a formatted Phase 1 report."""
        print("\n" + "=" * 60)
        print("PHASE 1 CHAOS ENGINEERING REPORT")
        print("=" * 60)
        print(f"Status: {report['status']}")
        print(f"Overall Result: {'PASS' if report['overall_passed'] else 'FAIL'}")
        print()

        summary = report["summary"]
        print("SUMMARY STATISTICS:")
        print(f"  Total Tests: {summary['total_tests']}")
        print(f"  Passed Tests: {summary['passed_tests']}")
        print(f"  Pass Rate: {summary['pass_rate']:.1%}")
        print(f"  Critical Failures: {summary['critical_failures']}")
        print(f"  Avg Response Time: {summary['avg_response_time_ms']:.1f}ms")
        print(f"  Avg Error Rate: {summary['avg_error_rate']:.2%}")

        print("\nTEST BREAKDOWN:")
        for test_type, stats in report["test_breakdown"].items():
            pass_rate = stats["passed"] / stats["total"]
            print(f"  {test_type}: {stats['passed']}/{stats['total']} ({pass_rate:.1%})")

        perf = report["performance_analysis"]
        print("\nPERFORMANCE ANALYSIS:")
        print(f"  Avg Response Time: {perf['avg_response_time_ms']:.1f}ms")
        print(f"  Median Response Time: {perf['median_response_time_ms']:.1f}ms")
        print(f"  Max Response Time: {perf['max_response_time_ms']:.1f}ms")
        print(f"  Response Time Variance: {perf['response_time_variance']:.2f}ms")
        print(f"  Avg Error Rate: {perf['avg_error_rate']:.1%}")

        if summary.get("issues"):
            print("\nISSUES IDENTIFIED:")
            for issue in summary["issues"]:
                print(f"  ❌ {issue}")

        if report.get("recommendations"):
            print("\nRECOMMENDATIONS:")
            for rec in report["recommendations"]:
                print(f"  💡 {rec}")

        print("\n" + "=" * 60)
