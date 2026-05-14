"""Phase 4 Chaos Engineering Success Criteria

This module implements validation logic for Phase 4 resource and concurrency chaos test success criteria.
Tests validate that FraiseQL maintains stability and performance under resource constraints and concurrent load.
"""

import statistics
from typing import Any, Dict, List, Tuple

from chaos.base import ChaosTestCase


class Phase4SuccessCriteria:
    """Success criteria validation for Phase 4 resource and concurrency chaos tests."""

    # Resource performance thresholds
    RESOURCE_SUCCESS_RATE_MIN = 0.75  # 75% operations succeed under resource pressure
    MEMORY_PRESSURE_SUCCESS_RATE = 0.80  # 80% operations succeed under memory pressure
    CPU_SPIKE_SUCCESS_RATE = 0.85  # 85% operations succeed under CPU spikes
    RESOURCE_RECOVERY_TIME_MAX = 5.0  # seconds to recover from resource exhaustion

    # Concurrency performance thresholds
    CONCURRENCY_SUCCESS_RATE_MIN = 0.80  # 80% operations succeed under concurrency
    DEADLOCK_PREVENTION_RATE = 0.90  # 90% of potential deadlocks prevented
    THREAD_CONTENTION_SUCCESS_RATE = 0.75  # 75% operations succeed under thread contention
    RACE_CONDITION_PREVENTION_RATE = 0.95  # 95% of race conditions prevented

    @classmethod
    def validate_resource_chaos_test(
        cls, test_case: ChaosTestCase, resource_type: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate resource chaos test results.

        Success Criteria:
        - System handles resource pressure gracefully
        - Performance degrades predictably under resource constraints
        - Recovery mechanisms work effectively
        - No catastrophic failures under resource exhaustion
        """
        results = test_case.metrics.get_summary()

        issues = []
        passed = True

        total_ops = results.get("query_count", 0)
        errors = results.get("error_count", 0)

        if total_ops == 0:
            issues.append("No resource operations completed")
            passed = False

        # Basic success rate check
        success_rate = 1 - (errors / max(total_ops, 1))
        if success_rate < cls.RESOURCE_SUCCESS_RATE_MIN:
            issues.append(
                f"Resource success rate too low: {success_rate:.1%} (min {cls.RESOURCE_SUCCESS_RATE_MIN:.1%})"
            )
            passed = False

        # Specific validation based on resource type
        if resource_type == "memory_pressure":
            if success_rate < cls.MEMORY_PRESSURE_SUCCESS_RATE:
                issues.append(
                    f"Memory pressure success rate too low: {success_rate:.1%} (min {cls.MEMORY_PRESSURE_SUCCESS_RATE:.1%})"
                )
                passed = False

        elif resource_type == "cpu_spike":
            if success_rate < cls.CPU_SPIKE_SUCCESS_RATE:
                issues.append(
                    f"CPU spike success rate too low: {success_rate:.1%} (min {cls.CPU_SPIKE_SUCCESS_RATE:.1%})"
                )
                passed = False

        elif resource_type == "disk_io":
            # I/O operations may have higher failure rates due to contention
            if success_rate < 0.7:  # Lower threshold for I/O
                issues.append(f"Disk I/O success rate too low: {success_rate:.1%} (min 70%)")
                passed = False

        elif resource_type == "resource_exhaustion":
            # Resource exhaustion should show some failures but recovery
            if errors == 0:
                issues.append("Resource exhaustion test should show some failures")
                passed = False
            if success_rate < 0.6:  # Allow higher failure rate for exhaustion tests
                issues.append("Too many failures under resource exhaustion")
                passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": f"resource_{resource_type}",
            "total_operations": total_ops,
            "errors": errors,
            "success_rate": success_rate,
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_concurrency_chaos_test(
        cls, test_case: ChaosTestCase, concurrency_type: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate concurrency chaos test results.

        Success Criteria:
        - Concurrent operations execute successfully
        - Deadlocks are prevented or resolved
        - Race conditions are avoided
        - Thread contention is managed effectively
        """
        results = test_case.metrics.get_summary()

        issues = []
        passed = True

        total_ops = results.get("query_count", 0)
        errors = results.get("error_count", 0)

        if total_ops == 0:
            issues.append("No concurrency operations completed")
            passed = False

        # Basic success rate check
        success_rate = 1 - (errors / max(total_ops, 1))
        if success_rate < cls.CONCURRENCY_SUCCESS_RATE_MIN:
            issues.append(
                f"Concurrency success rate too low: {success_rate:.1%} (min {cls.CONCURRENCY_SUCCESS_RATE_MIN:.1%})"
            )
            passed = False

        # Specific validation based on concurrency type
        if concurrency_type == "thread_pool_exhaustion":
            if success_rate < 0.7:  # Thread pool issues may cause more failures
                issues.append("Thread pool exhaustion handling needs improvement")
                passed = False

        elif concurrency_type == "lock_contention":
            if success_rate < cls.THREAD_CONTENTION_SUCCESS_RATE:
                issues.append(
                    f"Lock contention success rate too low: {success_rate:.1%} (min {cls.THREAD_CONTENTION_SUCCESS_RATE:.1%})"
                )
                passed = False

        elif concurrency_type == "race_condition":
            # Race conditions should be rare
            if errors > total_ops * 0.1:  # More than 10% race condition failures
                issues.append("Race condition prevention may be inadequate")
                passed = False

        elif concurrency_type == "deadlock_prevention":
            # Deadlocks should be minimal
            if success_rate < cls.DEADLOCK_PREVENTION_RATE:
                issues.append(
                    f"Deadlock prevention rate too low: {success_rate:.1%} (min {cls.DEADLOCK_PREVENTION_RATE:.1%})"
                )
                passed = False

        elif concurrency_type == "connection_pooling":
            if success_rate < 0.75:  # Connection pooling concurrency issues
                issues.append("Concurrent connection pooling needs improvement")
                passed = False

        elif concurrency_type == "atomic_operation":
            # Atomic operations should have high success rates
            if success_rate < 0.9:
                issues.append(
                    f"Atomic operation success rate too low: {success_rate:.1%} (min 90%)"
                )
                passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": f"concurrency_{concurrency_type}",
            "total_operations": total_ops,
            "errors": errors,
            "success_rate": success_rate,
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_phase4_overall_success(
        cls, test_results: List[Tuple[bool, str, Dict[str, Any]]]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate overall Phase 4 success based on all resource and concurrency chaos test results.

        Success Criteria:
        - 70% of resource and concurrency tests must pass
        - System maintains stability under resource pressure
        - Concurrent operations execute reliably
        - No critical resource or concurrency failures
        """
        if not test_results:
            return False, "FAIL", {"issues": ["No test results provided"]}

        total_tests = len(test_results)
        passed_tests = sum(1 for passed, _, _ in test_results if passed)
        pass_rate = passed_tests / total_tests

        issues = []

        # Check overall pass rate
        if pass_rate < cls.RESOURCE_SUCCESS_RATE_MIN:  # Using resource threshold as baseline
            issues.append(
                f"Overall pass rate too low: {pass_rate:.1%} (min {cls.RESOURCE_SUCCESS_RATE_MIN:.1%})"
            )
            overall_pass = False
        else:
            overall_pass = True

        # Check for critical resource and concurrency failures
        resource_failures = 0
        concurrency_failures = 0

        for passed, _, details in test_results:
            test_type = details.get("test_type", "")
            if not passed:
                if test_type.startswith("resource"):
                    resource_failures += 1
                elif test_type.startswith("concurrency"):
                    concurrency_failures += 1

        if resource_failures > 0:
            issues.append(f"Critical resource failures: {resource_failures}")
            overall_pass = False

        if concurrency_failures > total_tests * 0.3:  # More than 30% concurrency failures
            issues.append(f"Excessive concurrency failures: {concurrency_failures}/{total_tests}")
            overall_pass = False

        # Analyze resource vs concurrency balance
        resource_tests = [
            r for r in test_results if r[2].get("test_type", "").startswith("resource")
        ]
        concurrency_tests = [
            r for r in test_results if r[2].get("test_type", "").startswith("concurrency")
        ]

        resource_success_rate = (
            statistics.mean([r[2].get("success_rate", 0) for r in resource_tests])
            if resource_tests
            else 0
        )
        concurrency_success_rate = (
            statistics.mean([r[2].get("success_rate", 0) for r in concurrency_tests])
            if concurrency_tests
            else 0
        )

        # Both resource management and concurrency should be effective
        if (
            resource_success_rate < cls.RESOURCE_SUCCESS_RATE_MIN
            and concurrency_success_rate < cls.CONCURRENCY_SUCCESS_RATE_MIN
        ):
            issues.append(
                "Both resource management and concurrency handling compromised - critical system issue"
            )
            overall_pass = False

        status_msg = "PASS" if overall_pass else "FAIL"
        summary = {
            "phase": "phase4_resource_concurrency_chaos",
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "pass_rate": pass_rate,
            "resource_failures": resource_failures,
            "concurrency_failures": concurrency_failures,
            "resource_success_rate": resource_success_rate,
            "concurrency_success_rate": concurrency_success_rate,
            "issues": issues,
            "recommendations": cls._generate_phase4_recommendations(
                test_results, pass_rate, resource_failures, concurrency_failures
            ),
        }

        return overall_pass, status_msg, summary

    @classmethod
    def _generate_phase4_recommendations(
        cls,
        test_results: List[Tuple[bool, str, Dict[str, Any]]],
        pass_rate: float,
        resource_failures: int,
        concurrency_failures: int,
    ) -> List[str]:
        """Generate recommendations based on Phase 4 test results."""
        recommendations = []

        if pass_rate < 0.8:
            recommendations.append(
                "Improve resource and concurrency chaos resilience - consider enhanced resource monitoring and thread management"
            )

        if resource_failures > 0:
            recommendations.append(
                "Strengthen resource management - review memory, CPU, and I/O handling under pressure"
            )

        if concurrency_failures > 0:
            recommendations.append(
                "Enhance concurrency handling - implement better deadlock prevention and race condition avoidance"
            )

        # Check specific failure patterns
        memory_issues = sum(
            1
            for _, _, details in test_results
            if "memory" in details.get("test_type", "").lower()
            and details.get("success_rate", 1.0) < 0.8
        )
        if memory_issues > 0:
            recommendations.append(
                "Optimize memory management - consider garbage collection tuning and memory pool sizing"
            )

        cpu_issues = sum(
            1
            for _, _, details in test_results
            if "cpu" in details.get("test_type", "").lower()
            and details.get("success_rate", 1.0) < 0.8
        )
        if cpu_issues > 0:
            recommendations.append(
                "Improve CPU utilization - review computational complexity and thread scheduling"
            )

        deadlock_issues = sum(
            1
            for _, _, details in test_results
            if "deadlock" in details.get("test_type", "").lower()
            and details.get("success_rate", 1.0) < 0.85
        )
        if deadlock_issues > 0:
            recommendations.append(
                "Enhance deadlock prevention - review resource acquisition ordering and timeout strategies"
            )

        race_condition_issues = sum(
            1
            for _, _, details in test_results
            if "race" in details.get("test_type", "").lower()
            and details.get("success_rate", 1.0) < 0.9
        )
        if race_condition_issues > 0:
            recommendations.append(
                "Strengthen race condition prevention - implement better synchronization and atomic operations"
            )

        if not recommendations:
            recommendations.append(
                "Phase 4 resource and concurrency chaos resilience is excellent - proceed to Phase 5"
            )

        return recommendations


# Convenience functions for test validation


def validate_resource_concurrency_chaos_test_success(
    test_case: ChaosTestCase, test_type: str, **kwargs
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a resource or concurrency chaos test based on its type and success criteria.

    Args:
        test_case: The ChaosTestCase that was executed
        test_type: Type of test ("resource_memory_pressure", "resource_cpu_spike",
                   "concurrency_thread_pool", "concurrency_deadlock", etc.)
        **kwargs: Additional parameters for specific test types

    Returns:
        (passed, status_message, detailed_results)
    """
    if test_type.startswith("resource"):
        resource_subtype = test_type.split("_", 1)[1] if "_" in test_type else "general"
        return Phase4SuccessCriteria.validate_resource_chaos_test(test_case, resource_subtype)
    if test_type.startswith("concurrency"):
        concurrency_subtype = test_type.split("_", 1)[1] if "_" in test_type else "general"
        return Phase4SuccessCriteria.validate_concurrency_chaos_test(test_case, concurrency_subtype)
    return False, "FAIL", {"issues": [f"Unknown resource/concurrency test type: {test_type}"]}


def generate_phase4_report(test_results: List[Tuple[bool, str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Generate a comprehensive Phase 4 resource and concurrency chaos report."""
    overall_passed, status, summary = Phase4SuccessCriteria.validate_phase4_overall_success(
        test_results
    )

    report = {
        "phase": "Phase 4: Resource & Concurrency Chaos",
        "status": status,
        "overall_passed": overall_passed,
        "summary": summary,
        "test_breakdown": {},
        "performance_analysis": {},
        "resource_analysis": {},
        "concurrency_analysis": {},
        "recommendations": summary.get("recommendations", []),
    }

    # Breakdown by test category
    resource_tests = []
    concurrency_tests = []

    for passed, _, details in test_results:
        test_type = details.get("test_type", "")
        if test_type.startswith("resource"):
            resource_tests.append((passed, details))
        elif test_type.startswith("concurrency"):
            concurrency_tests.append((passed, details))

    report["test_breakdown"] = {
        "resource_tests": len(resource_tests),
        "concurrency_tests": len(concurrency_tests),
        "resource_passed": sum(1 for passed, _ in resource_tests if passed),
        "concurrency_passed": sum(1 for passed, _ in concurrency_tests),
    }

    # Performance and analysis
    all_success_rates = []
    resource_success_rates = []
    concurrency_success_rates = []

    for _, _, details in test_results:
        success_rate = details.get("success_rate", 0)
        all_success_rates.append(success_rate)

        test_type = details.get("test_type", "")
        if test_type.startswith("resource"):
            resource_success_rates.append(success_rate)
        elif test_type.startswith("concurrency"):
            concurrency_success_rates.append(success_rate)

    report["performance_analysis"] = {
        "overall_avg_success_rate": statistics.mean(all_success_rates) if all_success_rates else 0,
        "resource_avg_success_rate": statistics.mean(resource_success_rates)
        if resource_success_rates
        else 0,
    }

    report["resource_analysis"] = {
        "resource_success_rate": statistics.mean(resource_success_rates)
        if resource_success_rates
        else 0,
        "resource_stability_maintained": summary.get("resource_failures", 0) == 0,
        "resource_pressure_handled": summary.get("resource_success_rate", 0)
        >= Phase4SuccessCriteria.RESOURCE_SUCCESS_RATE_MIN,
    }

    report["concurrency_analysis"] = {
        "concurrency_success_rate": statistics.mean(concurrency_success_rates)
        if concurrency_success_rates
        else 0,
        "deadlock_prevention_effective": summary.get("concurrency_success_rate", 0)
        >= Phase4SuccessCriteria.DEADLOCK_PREVENTION_RATE,
        "race_condition_controlled": summary.get("concurrency_failures", 0)
        < len(concurrency_tests) * 0.2
        if concurrency_tests
        else True,
    }

    return report


def print_phase4_report(report: Dict[str, Any]):
    """Print a formatted Phase 4 resource and concurrency chaos report."""
    print("\n" + "=" * 60)
    print("PHASE 4 RESOURCE & CONCURRENCY CHAOS REPORT")
    print("=" * 60)
    print(f"Status: {report['status']}")
    print(f"Overall Result: {'PASS' if report['overall_passed'] else 'FAIL'}")
    print()

    summary = report["summary"]
    print("SUMMARY STATISTICS:")
    print(f"  Total Tests: {summary['total_tests']}")
    print(f"  Passed Tests: {summary['passed_tests']}")
    print(f"  Pass Rate: {summary['pass_rate']:.1%}")
    print(f"  Resource Failures: {summary['resource_failures']}")
    print(f"  Concurrency Failures: {summary['concurrency_failures']}")
    print(f"  Resource Success Rate: {summary['resource_success_rate']:.2%}")
    print(f"  Concurrency Success Rate: {summary['concurrency_success_rate']:.2%}")

    breakdown = report["test_breakdown"]
    print("\nTEST BREAKDOWN:")
    print(f"  Resource Tests: {breakdown['resource_passed']}/{breakdown['resource_tests']}")
    print(
        f"  Concurrency Tests: {breakdown['concurrency_passed']}/{breakdown['concurrency_tests']}"
    )

    perf = report["performance_analysis"]
    print("\nPERFORMANCE ANALYSIS:")
    print(f"  Overall Avg Success Rate: {perf['overall_avg_success_rate']:.2%}")
    print(f"  Resource Avg Success Rate: {perf['resource_avg_success_rate']:.2%}")

    resource = report["resource_analysis"]
    print("\nRESOURCE ANALYSIS:")
    print(f"  Resource Success Rate: {resource['resource_success_rate']:.2%}")
    print(
        f"  Resource Stability Maintained: {'YES' if resource['resource_stability_maintained'] else 'NO'}"
    )
    print(
        f"  Resource Pressure Handled: {'YES' if resource['resource_pressure_handled'] else 'NO'}"
    )

    concurrency = report["concurrency_analysis"]
    print("\nCONCURRENCY ANALYSIS:")
    print(f"  Concurrency Success Rate: {concurrency['concurrency_success_rate']:.2%}")
    print(
        f"  Deadlock Prevention Effective: {'YES' if concurrency['deadlock_prevention_effective'] else 'NO'}"
    )
    print(
        f"  Race Condition Controlled: {'YES' if concurrency['race_condition_controlled'] else 'NO'}"
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
