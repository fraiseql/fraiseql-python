"""Phase 2 Chaos Engineering Success Criteria

This module implements validation logic for Phase 2 database chaos test success criteria.
Tests validate that FraiseQL maintains data consistency and handles database failures gracefully.
"""

import statistics
from typing import Any, Dict, List, Tuple

from chaos.base import ChaosTestCase


class Phase2SuccessCriteria:
    """Success criteria validation for Phase 2 database chaos tests."""

    # Database performance thresholds
    MAX_QUERY_LATENCY_DEGRADATION = 10.0  # seconds (10000ms)
    MIN_SUCCESS_RATE = 0.70  # 70% operations must succeed under database chaos
    MAX_ERROR_RATE_SPIKE = 0.60  # Error rate can increase by max 60% under chaos
    DEADLOCK_RESOLUTION_RATE = 0.80  # 80% of deadlocks should be resolved
    SERIALIZATION_SUCCESS_RATE = 0.75  # 75% operations should succeed despite conflicts

    # Data consistency thresholds
    MAX_CONSTRAINT_VIOLATION_RATE = 0.40  # Max 40% constraint violations acceptable
    MAX_ROLLBACK_RATE = 0.50  # Max 50% transaction rollbacks acceptable
    CASCADE_FAILURE_PREVENTION_RATE = 0.95  # 95% of cascades should be prevented

    @classmethod
    def validate_query_execution_chaos_test(
        cls, test_case: ChaosTestCase, query_type: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate query execution chaos test results.

        Success Criteria:
        - System handles slow queries and timeouts appropriately
        - Deadlocks are detected and resolved with retries
        - Serialization failures are handled with exponential backoff
        - Pool exhaustion is managed gracefully
        """
        results = test_case.metrics.get_summary()

        issues = []
        passed = True

        total_ops = results.get("query_count", 0)
        errors = results.get("error_count", 0)
        success_rate = 1 - (errors / max(total_ops, 1))

        # Check success rate
        if success_rate < cls.MIN_SUCCESS_RATE:
            issues.append(".1f")
            passed = False

        # Check error rate spike (compare to baseline if available)
        if errors > total_ops * 0.5:  # More than 50% errors
            issues.append("Excessive error rate under query chaos")
            passed = False

        # Specific checks based on query type
        if query_type == "timeout":
            # Timeout tests should show some failures but reasonable success rate
            if errors == 0:
                issues.append("Timeout test should show some timeout errors")
                passed = False
        elif query_type == "deadlock":
            # Deadlock tests should show some errors but resolution
            if errors == 0:
                issues.append("Deadlock test should show some deadlock errors")
                passed = False
        elif query_type == "serialization":
            # Serialization tests should show conflicts but eventual success
            if success_rate < cls.SERIALIZATION_SUCCESS_RATE:
                issues.append(".1f")
                passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": f"query_execution_{query_type}",
            "total_operations": total_ops,
            "errors": errors,
            "success_rate": success_rate,
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_data_consistency_chaos_test(
        cls, test_case: ChaosTestCase, consistency_type: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate data consistency chaos test results.

        Success Criteria:
        - Transaction rollbacks are handled gracefully
        - Partial update failures don't corrupt data
        - Constraint violations return appropriate errors
        - Isolation anomalies are prevented or detected
        - Cascading failures are contained
        """
        results = test_case.metrics.get_summary()

        issues = []
        passed = True

        total_ops = results.get("query_count", 0)
        errors = results.get("error_count", 0)

        # Basic validation
        if total_ops == 0:
            issues.append("No operations completed in consistency test")
            passed = False

        # Specific validation based on consistency type
        if consistency_type == "transaction_rollback":
            rollback_rate = errors / max(total_ops, 1)
            if rollback_rate > cls.MAX_ROLLBACK_RATE:
                issues.append(".1f")
                passed = False
            if rollback_rate == 0:
                issues.append("Transaction rollback test should show some rollbacks")
                passed = False

        elif consistency_type == "constraint_violation":
            violation_rate = errors / max(total_ops, 1)
            if violation_rate > cls.MAX_CONSTRAINT_VIOLATION_RATE:
                issues.append(".1f")
                passed = False
            if violation_rate == 0:
                issues.append("Constraint violation test should show some violations")
                passed = False

        elif consistency_type == "partial_update":
            # Partial updates should have some failures but be contained
            if errors == 0:
                issues.append("Partial update test should show some failures")
                passed = False
            if errors > total_ops * 0.7:  # More than 70% failures
                issues.append("Too many partial update failures")
                passed = False

        elif consistency_type == "cascading_failure":
            # Cascading failures should be rare
            failure_rate = errors / max(total_ops, 1)
            if failure_rate > (1 - cls.CASCADE_FAILURE_PREVENTION_RATE):
                issues.append(".1f")
                passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": f"data_consistency_{consistency_type}",
            "total_operations": total_ops,
            "errors": errors,
            "error_rate": errors / max(total_ops, 1),
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_phase2_overall_success(
        cls, test_results: List[Tuple[bool, str, Dict[str, Any]]]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate overall Phase 2 success based on all database chaos test results.

        Success Criteria:
        - 70% of database chaos tests must pass
        - No critical data consistency failures
        - Query execution remains reasonably reliable
        - Error rates stay within acceptable bounds
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

        # Check for critical consistency failures
        consistency_failures = 0
        execution_failures = 0

        for passed, _, details in test_results:
            test_type = details.get("test_type", "")
            if not passed:
                if "consistency" in test_type:
                    consistency_failures += 1
                elif "execution" in test_type:
                    execution_failures += 1

        if consistency_failures > 0:
            issues.append(f"Critical consistency failures: {consistency_failures}")
            overall_pass = False

        if execution_failures > total_tests * 0.5:  # More than half execution tests fail
            issues.append(f"Excessive query execution failures: {execution_failures}/{total_tests}")
            overall_pass = False

        # Aggregate performance metrics
        all_success_rates = []
        all_error_rates = []

        for _, _, details in test_results:
            if "success_rate" in details:
                all_success_rates.append(details["success_rate"])
            if "error_rate" in details:
                all_error_rates.append(details["error_rate"])

        avg_success_rate = statistics.mean(all_success_rates) if all_success_rates else 0
        avg_error_rate = statistics.mean(all_error_rates) if all_error_rates else 0

        status_msg = "PASS" if overall_pass else "FAIL"
        summary = {
            "phase": "phase2_database_chaos",
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "pass_rate": pass_rate,
            "consistency_failures": consistency_failures,
            "execution_failures": execution_failures,
            "avg_success_rate": avg_success_rate,
            "avg_error_rate": avg_error_rate,
            "issues": issues,
            "recommendations": cls._generate_phase2_recommendations(
                test_results, pass_rate, consistency_failures
            ),
        }

        return overall_pass, status_msg, summary

    @classmethod
    def _generate_phase2_recommendations(
        cls,
        test_results: List[Tuple[bool, str, Dict[str, Any]]],
        pass_rate: float,
        consistency_failures: int,
    ) -> List[str]:
        """Generate recommendations based on Phase 2 test results."""
        recommendations = []

        if pass_rate < 0.8:
            recommendations.append(
                "Improve database chaos resilience - consider enhanced retry logic and timeout handling"
            )

        if consistency_failures > 0:
            recommendations.append(
                "Address data consistency issues - review transaction handling and constraint validation"
            )

        # Check specific failure patterns
        execution_issues = sum(
            1
            for _, _, details in test_results
            if details.get("test_type", "").startswith("query_execution")
            and details.get("success_rate", 1.0) < 0.7
        )
        if execution_issues > 0:
            recommendations.append(
                "Optimize query execution under chaos - review connection pooling and deadlock handling"
            )

        consistency_issues = sum(
            1
            for _, _, details in test_results
            if details.get("test_type", "").startswith("data_consistency")
            and details.get("error_rate", 0) > 0.4
        )
        if consistency_issues > 0:
            recommendations.append(
                "Strengthen data consistency guarantees - implement better transaction isolation"
            )

        if not recommendations:
            recommendations.append(
                "Phase 2 database chaos resilience is excellent - proceed to Phase 3"
            )

        return recommendations


# Convenience functions for test validation


def validate_database_chaos_test_success(
    test_case: ChaosTestCase, test_type: str, **kwargs
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a database chaos test based on its type and success criteria.

    Args:
        test_case: The ChaosTestCase that was executed
        test_type: Type of test ("query_execution_timeout", "query_execution_deadlock",
                   "data_consistency_transaction", etc.)
        **kwargs: Additional parameters for specific test types

    Returns:
        (passed, status_message, detailed_results)
    """
    if test_type.startswith("query_execution"):
        query_subtype = test_type.split("_")[-1]  # Extract subtype (timeout, deadlock, etc.)
        return Phase2SuccessCriteria.validate_query_execution_chaos_test(test_case, query_subtype)
    if test_type.startswith("data_consistency"):
        consistency_subtype = test_type.split("_")[
            -1
        ]  # Extract subtype (transaction, constraint, etc.)
        return Phase2SuccessCriteria.validate_data_consistency_chaos_test(
            test_case, consistency_subtype
        )
    return False, "FAIL", {"issues": [f"Unknown database test type: {test_type}"]}


def generate_phase2_report(test_results: List[Tuple[bool, str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Generate a comprehensive Phase 2 database chaos report."""
    overall_passed, status, summary = Phase2SuccessCriteria.validate_phase2_overall_success(
        test_results
    )

    report = {
        "phase": "Phase 2: Database & Query Chaos",
        "status": status,
        "overall_passed": overall_passed,
        "summary": summary,
        "test_breakdown": {},
        "performance_analysis": {},
        "consistency_analysis": {},
        "recommendations": summary.get("recommendations", []),
    }

    # Breakdown by test category
    execution_tests = []
    consistency_tests = []

    for passed, _, details in test_results:
        test_type = details.get("test_type", "")
        if test_type.startswith("query_execution"):
            execution_tests.append((passed, details))
        elif test_type.startswith("data_consistency"):
            consistency_tests.append((passed, details))

    report["test_breakdown"] = {
        "execution_tests": len(execution_tests),
        "consistency_tests": len(consistency_tests),
        "execution_passed": sum(1 for passed, _ in execution_tests if passed),
        "consistency_passed": sum(1 for passed, _ in consistency_tests if passed),
    }

    # Performance and consistency analysis
    all_success_rates = []
    all_error_rates = []
    execution_success_rates = []
    consistency_error_rates = []

    for passed, _, details in test_results:
        success_rate = details.get("success_rate", 0)
        error_rate = details.get("error_rate", 0)

        all_success_rates.append(success_rate)
        all_error_rates.append(error_rate)

        test_type = details.get("test_type", "")
        if test_type.startswith("query_execution"):
            execution_success_rates.append(success_rate)
        elif test_type.startswith("data_consistency"):
            consistency_error_rates.append(error_rate)

    report["performance_analysis"] = {
        "overall_avg_success_rate": statistics.mean(all_success_rates) if all_success_rates else 0,
        "overall_avg_error_rate": statistics.mean(all_error_rates) if all_error_rates else 0,
        "execution_avg_success_rate": statistics.mean(execution_success_rates)
        if execution_success_rates
        else 0,
    }

    report["consistency_analysis"] = {
        "consistency_avg_error_rate": statistics.mean(consistency_error_rates)
        if consistency_error_rates
        else 0,
        "consistency_max_error_rate": max(consistency_error_rates)
        if consistency_error_rates
        else 0,
        "data_integrity_maintained": summary.get("consistency_failures", 0) == 0,
    }

    return report


def print_phase2_report(report: Dict[str, Any]):
    """Print a formatted Phase 2 database chaos report."""
    print("\n" + "=" * 60)
    print("PHASE 2 DATABASE CHAOS ENGINEERING REPORT")
    print("=" * 60)
    print(f"Status: {report['status']}")
    print(f"Overall Result: {'PASS' if report['overall_passed'] else 'FAIL'}")
    print()

    summary = report["summary"]
    print("SUMMARY STATISTICS:")
    print(f"  Total Tests: {summary['total_tests']}")
    print(f"  Passed Tests: {summary['passed_tests']}")
    print(".1f")
    print(f"  Execution Failures: {summary['execution_failures']}")
    print(f"  Consistency Failures: {summary['consistency_failures']}")
    print(".2f")
    print(".2f")

    breakdown = report["test_breakdown"]
    print("\nTEST BREAKDOWN:")
    print(
        f"  Query Execution Tests: {breakdown['execution_passed']}/{breakdown['execution_tests']}"
    )
    print(
        f"  Data Consistency Tests: {breakdown['consistency_passed']}/{breakdown['consistency_tests']}"
    )

    perf = report["performance_analysis"]
    print("\nPERFORMANCE ANALYSIS:")
    print(".2f")
    print(".2f")
    print(".2f")

    consistency = report["consistency_analysis"]
    print("\nCONSISTENCY ANALYSIS:")
    print(".2f")
    print(".2f")
    print(
        f"  Data Integrity Maintained: {'YES' if consistency['data_integrity_maintained'] else 'NO'}"
    )

    if summary.get("issues"):
        print("\nISSUES IDENTIFIED:")
        for issue in summary["issues"]:
            print(f"  ❌ {issue}")

    if report.get("recommendations"):
        print("\nRECOMMENDATIONS:")
        for rec in report["recommendations"]:
            print(f"  💡 {rec}")

    print("\n" + "=" * 60)
