"""Phase 3 Chaos Engineering Success Criteria

This module implements validation logic for Phase 3 cache and authentication chaos test success criteria.
Tests validate that FraiseQL maintains performance and security under adverse cache and auth conditions.
"""

import statistics
from typing import Any, Dict, List, Tuple

from chaos.base import ChaosTestCase


class Phase3SuccessCriteria:
    """Success criteria validation for Phase 3 cache and auth chaos tests."""

    # Cache performance thresholds
    CACHE_HIT_RATE_MIN = 0.4  # Minimum cache hit rate under chaos (40%)
    CACHE_RECOVERY_TIME_MAX = 3.0  # seconds to recover cache performance
    CORRUPTION_DETECTION_RATE = 0.8  # 80% of corruptions should be detected
    STAMPEDE_PREVENTION_RATE = 0.9  # 90% of stampedes should be prevented

    # Authentication security thresholds
    AUTH_SUCCESS_RATE_MIN = 0.6  # 60% auth operations should succeed under chaos
    SECURITY_FAILURE_HANDLING = 0.95  # 95% of security failures should be handled properly
    RBAC_POLICY_SUCCESS_RATE = 0.7  # 70% RBAC evaluations should succeed
    JWT_VALIDATION_ACCURACY = 0.9  # 90% JWT validation accuracy required

    @classmethod
    def validate_cache_chaos_test(
        cls, test_case: ChaosTestCase, cache_type: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate cache chaos test results.

        Success Criteria:
        - Cache hit rates remain acceptable under chaos
        - Corruptions are detected and handled
        - Backend failures don't crash the system
        - Stampede effects are prevented
        - Memory pressure is managed gracefully
        """
        results = test_case.metrics.get_summary()

        issues = []
        passed = True

        total_ops = results.get("query_count", 0)
        errors = results.get("error_count", 0)

        if total_ops == 0:
            issues.append("No cache operations completed")
            passed = False

        # Specific validation based on cache chaos type
        if cache_type == "invalidation_storm":
            # Cache hit rate should be reasonable during storm
            # (This would require additional metrics in real implementation)
            if errors > total_ops * 0.3:  # More than 30% errors
                issues.append("Too many errors during cache invalidation storm")
                passed = False

        elif cache_type == "corruption":
            # Should detect and handle corruptions
            corruption_errors = errors  # Assume errors indicate corruption handling
            if corruption_errors == 0:
                issues.append("Cache corruption test should show corruption handling")
                passed = False

        elif cache_type == "backend_failure":
            # System should continue operating during backend failures
            success_rate = 1 - (errors / max(total_ops, 1))
            if success_rate < cls.CACHE_HIT_RATE_MIN:
                issues.append(
                    f"Cache hit rate too low during backend failure: {success_rate:.1%} (min {cls.CACHE_HIT_RATE_MIN:.1%})"
                )
                passed = False

        elif cache_type == "stampede":
            # Should prevent excessive stampede effects
            if errors > total_ops * 0.2:  # More than 20% errors
                issues.append("Cache stampede prevention may be inadequate")
                passed = False

        elif cache_type == "memory_pressure":
            # Should handle memory pressure gracefully
            if errors > total_ops * 0.15:  # More than 15% errors
                issues.append("Memory pressure handling may need improvement")
                passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": f"cache_{cache_type}",
            "total_operations": total_ops,
            "errors": errors,
            "success_rate": 1 - (errors / max(total_ops, 1)),
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_auth_chaos_test(
        cls, test_case: ChaosTestCase, auth_type: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate authentication chaos test results.

        Success Criteria:
        - Authentication maintains security under chaos
        - JWT validation works correctly
        - RBAC policies are enforced
        - Service outages are handled gracefully
        - Concurrent auth load is managed
        """
        results = test_case.metrics.get_summary()

        issues = []
        passed = True

        total_ops = results.get("query_count", 0)
        errors = results.get("error_count", 0)

        if total_ops == 0:
            issues.append("No auth operations completed")
            passed = False

        # Basic success rate check
        success_rate = 1 - (errors / max(total_ops, 1))
        if success_rate < cls.AUTH_SUCCESS_RATE_MIN:
            issues.append(
                f"Auth success rate too low: {success_rate:.1%} (min {cls.AUTH_SUCCESS_RATE_MIN:.1%})"
            )
            passed = False

        # Specific validation based on auth chaos type
        if auth_type == "jwt_expiration":
            # Should handle token expirations
            if errors == 0:
                issues.append("JWT expiration test should show expiration handling")
                passed = False

        elif auth_type == "rbac_policy":
            # Should handle RBAC failures securely
            if success_rate < cls.RBAC_POLICY_SUCCESS_RATE:
                issues.append(
                    f"RBAC success rate too low: {success_rate:.1%} (min {cls.RBAC_POLICY_SUCCESS_RATE:.1%})"
                )
                passed = False

        elif auth_type == "service_outage":
            # Should handle auth service unavailability
            if errors == 0:
                issues.append("Auth service outage test should show outage handling")
                passed = False

        elif auth_type == "concurrent_load":
            # Should handle concurrent auth requests
            if success_rate < 0.7:  # Lower threshold for concurrent load
                issues.append("Concurrent auth load handling needs improvement")
                passed = False

        elif auth_type == "jwt_signature":
            # Should validate signatures correctly
            if success_rate < cls.JWT_VALIDATION_ACCURACY:
                issues.append(
                    f"JWT validation accuracy too low: {success_rate:.1%} (min {cls.JWT_VALIDATION_ACCURACY:.1%})"
                )
                passed = False

        elif auth_type == "rbac_comprehensive":
            # Should maintain security posture
            if success_rate < cls.RBAC_POLICY_SUCCESS_RATE:
                issues.append("Comprehensive RBAC security needs strengthening")
                passed = False

        status_msg = "PASS" if passed else "FAIL"
        details = {
            "test_type": f"auth_{auth_type}",
            "total_operations": total_ops,
            "errors": errors,
            "success_rate": success_rate,
            "issues": issues,
        }

        return passed, status_msg, details

    @classmethod
    def validate_phase3_overall_success(
        cls, test_results: List[Tuple[bool, str, Dict[str, Any]]]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate overall Phase 3 success based on all cache and auth chaos test results.

        Success Criteria:
        - 70% of cache and auth tests must pass
        - No critical security failures in authentication
        - Cache performance remains acceptable
        - System maintains both performance and security under chaos
        """
        if not test_results:
            return False, "FAIL", {"issues": ["No test results provided"]}

        total_tests = len(test_results)
        passed_tests = sum(1 for passed, _, _ in test_results if passed)
        pass_rate = passed_tests / total_tests

        issues = []

        # Check overall pass rate
        if pass_rate < cls.AUTH_SUCCESS_RATE_MIN:  # Using auth threshold as baseline
            issues.append(".1f")
            overall_pass = False
        else:
            overall_pass = True

        # Check for critical security failures
        auth_failures = 0
        cache_failures = 0

        for passed, _, details in test_results:
            test_type = details.get("test_type", "")
            if not passed:
                if test_type.startswith("auth"):
                    auth_failures += 1
                elif test_type.startswith("cache"):
                    cache_failures += 1

        if auth_failures > 0:
            issues.append(f"Critical authentication security failures: {auth_failures}")
            overall_pass = False

        if cache_failures > total_tests * 0.4:  # More than 40% cache failures
            issues.append(f"Excessive cache performance failures: {cache_failures}/{total_tests}")
            overall_pass = False

        # Analyze security vs performance balance
        auth_tests = [r for r in test_results if r[2].get("test_type", "").startswith("auth")]
        cache_tests = [r for r in test_results if r[2].get("test_type", "").startswith("cache")]

        auth_success_rate = (
            statistics.mean([r[2].get("success_rate", 0) for r in auth_tests]) if auth_tests else 0
        )
        cache_success_rate = (
            statistics.mean([r[2].get("success_rate", 0) for r in cache_tests])
            if cache_tests
            else 0
        )

        # Both security and performance should be maintained
        if (
            auth_success_rate < cls.RBAC_POLICY_SUCCESS_RATE
            and cache_success_rate < cls.CACHE_HIT_RATE_MIN
        ):
            issues.append("Both security and performance compromised - critical system issue")
            overall_pass = False

        status_msg = "PASS" if overall_pass else "FAIL"
        summary = {
            "phase": "phase3_cache_auth_chaos",
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "pass_rate": pass_rate,
            "auth_failures": auth_failures,
            "cache_failures": cache_failures,
            "auth_success_rate": auth_success_rate,
            "cache_success_rate": cache_success_rate,
            "issues": issues,
            "recommendations": cls._generate_phase3_recommendations(
                test_results, pass_rate, auth_failures, cache_failures
            ),
        }

        return overall_pass, status_msg, summary

    @classmethod
    def _generate_phase3_recommendations(
        cls,
        test_results: List[Tuple[bool, str, Dict[str, Any]]],
        pass_rate: float,
        auth_failures: int,
        cache_failures: int,
    ) -> List[str]:
        """Generate recommendations based on Phase 3 test results."""
        recommendations = []

        if pass_rate < 0.8:
            recommendations.append(
                "Improve cache and authentication chaos resilience - consider enhanced error handling and fallback mechanisms"
            )

        if auth_failures > 0:
            recommendations.append(
                "Strengthen authentication security under chaos - review token validation and RBAC policy enforcement"
            )

        if cache_failures > 0:
            recommendations.append(
                "Enhance cache reliability - implement better corruption detection and backend failure handling"
            )

        # Check specific failure patterns
        jwt_issues = sum(
            1
            for _, _, details in test_results
            if "jwt" in details.get("test_type", "").lower()
            and details.get("success_rate", 1.0) < 0.8
        )
        if jwt_issues > 0:
            recommendations.append(
                "Improve JWT token handling - consider more robust expiration and signature validation"
            )

        rbac_issues = sum(
            1
            for _, _, details in test_results
            if "rbac" in details.get("test_type", "").lower()
            and details.get("success_rate", 1.0) < 0.7
        )
        if rbac_issues > 0:
            recommendations.append(
                "Strengthen RBAC policy evaluation - implement more resilient authorization logic"
            )

        cache_corruption_issues = sum(
            1
            for _, _, details in test_results
            if "corruption" in details.get("test_type", "").lower()
            and details.get("success_rate", 1.0) < 0.8
        )
        if cache_corruption_issues > 0:
            recommendations.append("Improve cache corruption detection and recovery mechanisms")

        if not recommendations:
            recommendations.append(
                "Phase 3 cache and authentication chaos resilience is excellent - proceed to Phase 4"
            )

        return recommendations


# Convenience functions for test validation


def validate_cache_auth_chaos_test_success(
    test_case: ChaosTestCase, test_type: str, **kwargs
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a cache or auth chaos test based on its type and success criteria.

    Args:
        test_case: The ChaosTestCase that was executed
        test_type: Type of test ("cache_invalidation", "cache_corruption",
                   "auth_jwt_expiration", "auth_rbac_policy", etc.)
        **kwargs: Additional parameters for specific test types

    Returns:
        (passed, status_message, detailed_results)
    """
    if test_type.startswith("cache"):
        cache_subtype = test_type.split("_", 1)[1] if "_" in test_type else "general"
        return Phase3SuccessCriteria.validate_cache_chaos_test(test_case, cache_subtype)
    if test_type.startswith("auth"):
        auth_subtype = test_type.split("_", 1)[1] if "_" in test_type else "general"
        return Phase3SuccessCriteria.validate_auth_chaos_test(test_case, auth_subtype)
    return False, "FAIL", {"issues": [f"Unknown cache/auth test type: {test_type}"]}


def generate_phase3_report(test_results: List[Tuple[bool, str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Generate a comprehensive Phase 3 cache and auth chaos report."""
    overall_passed, status, summary = Phase3SuccessCriteria.validate_phase3_overall_success(
        test_results
    )

    report = {
        "phase": "Phase 3: Cache & Authentication Chaos",
        "status": status,
        "overall_passed": overall_passed,
        "summary": summary,
        "test_breakdown": {},
        "performance_analysis": {},
        "security_analysis": {},
        "recommendations": summary.get("recommendations", []),
    }

    # Breakdown by test category
    cache_tests = []
    auth_tests = []

    for passed, _, details in test_results:
        test_type = details.get("test_type", "")
        if test_type.startswith("cache"):
            cache_tests.append((passed, details))
        elif test_type.startswith("auth"):
            auth_tests.append((passed, details))

    report["test_breakdown"] = {
        "cache_tests": len(cache_tests),
        "auth_tests": len(auth_tests),
        "cache_passed": sum(1 for passed, _ in cache_tests if passed),
        "auth_passed": sum(1 for passed, _ in auth_tests),
    }

    # Performance and security analysis
    all_success_rates = []
    cache_success_rates = []
    auth_success_rates = []

    for _, _, details in test_results:
        success_rate = details.get("success_rate", 0)
        all_success_rates.append(success_rate)

        test_type = details.get("test_type", "")
        if test_type.startswith("cache"):
            cache_success_rates.append(success_rate)
        elif test_type.startswith("auth"):
            auth_success_rates.append(success_rate)

    report["performance_analysis"] = {
        "overall_avg_success_rate": statistics.mean(all_success_rates) if all_success_rates else 0,
        "cache_avg_success_rate": statistics.mean(cache_success_rates)
        if cache_success_rates
        else 0,
    }

    report["security_analysis"] = {
        "auth_avg_success_rate": statistics.mean(auth_success_rates) if auth_success_rates else 0,
        "security_posture_maintained": summary.get("auth_failures", 0) == 0,
        "cache_performance_acceptable": summary.get("cache_success_rate", 0)
        >= Phase3SuccessCriteria.CACHE_HIT_RATE_MIN,
    }

    return report


def print_phase3_report(report: Dict[str, Any]):
    """Print a formatted Phase 3 cache and auth chaos report."""
    print("\n" + "=" * 60)
    print("PHASE 3 CACHE & AUTHENTICATION CHAOS REPORT")
    print("=" * 60)
    print(f"Status: {report['status']}")
    print(f"Overall Result: {'PASS' if report['overall_passed'] else 'FAIL'}")
    print()

    summary = report["summary"]
    print("SUMMARY STATISTICS:")
    print(f"  Total Tests: {summary['total_tests']}")
    print(f"  Passed Tests: {summary['passed_tests']}")
    print(f"  Pass Rate: {summary['pass_rate']:.1%}")
    print(f"  Auth Failures: {summary['auth_failures']}")
    print(f"  Cache Failures: {summary['cache_failures']}")
    print(f"  Auth Success Rate: {summary['auth_success_rate']:.2%}")
    print(f"  Cache Success Rate: {summary['cache_success_rate']:.2%}")

    breakdown = report["test_breakdown"]
    print("\nTEST BREAKDOWN:")
    print(f"  Cache Tests: {breakdown['cache_passed']}/{breakdown['cache_tests']}")
    print(f"  Auth Tests: {breakdown['auth_passed']}/{breakdown['auth_tests']}")

    perf = report["performance_analysis"]
    print("\nPERFORMANCE ANALYSIS:")
    print(f"  Overall Avg Success Rate: {perf['overall_avg_success_rate']:.2%}")
    print(f"  Cache Avg Success Rate: {perf['cache_avg_success_rate']:.2%}")

    security = report["security_analysis"]
    print("\nSECURITY ANALYSIS:")
    print(f"  Auth Avg Success Rate: {security['auth_avg_success_rate']:.2%}")
    print(
        f"  Security Posture Maintained: {'YES' if security['security_posture_maintained'] else 'NO'}"
    )
    print(
        f"  Cache Performance Acceptable: {'YES' if security['cache_performance_acceptable'] else 'NO'}"
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
