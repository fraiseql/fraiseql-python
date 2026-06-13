"""Validation tests for adaptive auth chaos tests.

These tests verify that adaptive auth tests scale correctly across
different hardware profiles (LOW, MEDIUM, HIGH).
"""

import pytest
from chaos.adaptive_config import get_config_for_profile


class TestAdaptiveAuthValidation:
    """Validate auth tests work across all hardware profiles."""

    @pytest.mark.parametrize("profile", ["low", "medium", "high"])
    def test_jwt_expiration_scales_correctly(self, profile):
        """Verify JWT expiration test scales across profiles.

        Tests that iteration counts are appropriate for each profile:
        - LOW (0.5x): 5 iterations (minimum)
        - MEDIUM (1.0x): 10 iterations (baseline)
        - HIGH (4.0x): 40 iterations (maximum)
        """
        config = get_config_for_profile(profile)

        # Calculate expected iterations using same formula as test
        base_iterations = 10
        expected_iterations = max(5, int(base_iterations * config.load_multiplier))

        # Validate iteration counts
        if profile == "low":
            assert expected_iterations == 5, f"LOW profile should use 5 iterations, got {expected_iterations}"
            assert config.load_multiplier == 0.5, "LOW profile should have 0.5x multiplier"
        elif profile == "medium":
            assert expected_iterations == 10, f"MEDIUM profile should use 10 iterations, got {expected_iterations}"
            assert config.load_multiplier == 1.0, "MEDIUM profile should have 1.0x multiplier"
        elif profile == "high":
            assert expected_iterations == 40, f"HIGH profile should use 40 iterations, got {expected_iterations}"
            assert config.load_multiplier == 4.0, "HIGH profile should have 4.0x multiplier"

        # Validate iterations are meaningful (not too low)
        assert expected_iterations >= 5, "Iterations should never be less than 5"

        # Validate chaos effects would still occur
        # With 15% token expiration rate, we should see at least 1 expiration
        expected_expirations = expected_iterations * 0.15
        assert expected_expirations >= 0.75, (
            f"Profile {profile} may not experience enough expirations: "
            f"{expected_expirations:.2f} expected"
        )

    @pytest.mark.parametrize("profile", ["low", "medium", "high"])
    def test_jwt_signature_validation_scales_correctly(self, profile):
        """Verify JWT signature validation test scales across profiles.

        Tests that iteration counts are appropriate for each profile:
        - LOW (0.5x): 5 iterations (minimum)
        - MEDIUM (1.0x): 10 iterations (baseline)
        - HIGH (4.0x): 40 iterations (maximum)
        """
        config = get_config_for_profile(profile)

        # Calculate expected iterations using same formula as test
        base_iterations = 10
        expected_iterations = max(5, int(base_iterations * config.load_multiplier))

        # Validate iteration counts
        if profile == "low":
            assert expected_iterations == 5, f"LOW profile should use 5 iterations, got {expected_iterations}"
        elif profile == "medium":
            assert expected_iterations == 10, f"MEDIUM profile should use 10 iterations, got {expected_iterations}"
        elif profile == "high":
            assert expected_iterations == 40, f"HIGH profile should use 40 iterations, got {expected_iterations}"

        # Validate chaos effects would still occur
        # With 30% invalid tokens (15% invalid sig + 15% tampered), we should see failures
        expected_invalid = expected_iterations * 0.30
        assert expected_invalid >= 1.0, (
            f"Profile {profile} may not experience enough invalid tokens: "
            f"{expected_invalid:.2f} expected"
        )

        # At least 1 invalid signature expected (15% of iterations)
        expected_invalid_sigs = expected_iterations * 0.15
        assert expected_invalid_sigs >= 0.75, (
            f"Profile {profile} may not detect invalid signatures: "
            f"{expected_invalid_sigs:.2f} expected"
        )

    @pytest.mark.parametrize("profile", ["low", "medium", "high"])
    def test_config_timeout_scaling(self, profile):
        """Verify timeout scaling is inverse to hardware performance.

        Faster hardware → stricter timeouts
        Slower hardware → more lenient timeouts
        """
        config = get_config_for_profile(profile)

        # Validate timeout scaling (inverse to performance)
        if profile == "low":
            # LOW hardware gets longest timeouts
            assert config.timeout_seconds >= 5.0, "LOW profile should have lenient timeouts"
        elif profile == "medium":
            # MEDIUM hardware gets moderate timeouts
            assert 2.0 <= config.timeout_seconds <= 7.0, "MEDIUM profile should have moderate timeouts"
        elif profile == "high":
            # HIGH hardware gets strictest timeouts
            assert config.timeout_seconds <= 2.0, "HIGH profile should have strict timeouts"

        # Verify inverse relationship with multiplier
        # Higher multiplier (faster) → lower timeout
        expected_timeout_range = (1.0 / config.load_multiplier) * 5.0
        assert config.timeout_seconds <= expected_timeout_range * 1.5, (
            f"Timeout {config.timeout_seconds}s too high for {profile} "
            f"(expected ≤{expected_timeout_range * 1.5:.1f}s)"
        )

    @pytest.mark.parametrize("profile", ["low", "medium", "high"])
    def test_concurrent_requests_scaling(self, profile):
        """Verify concurrent request counts scale with hardware.

        Better hardware → more concurrent requests
        Weaker hardware → fewer concurrent requests
        """
        config = get_config_for_profile(profile)

        # Validate concurrent request scaling
        if profile == "low":
            assert config.concurrent_requests == 50, f"LOW profile should have 50 concurrent requests, got {config.concurrent_requests}"
        elif profile == "medium":
            assert config.concurrent_requests == 100, f"MEDIUM profile should have 100 concurrent requests, got {config.concurrent_requests}"
        elif profile == "high":
            assert config.concurrent_requests == 400, f"HIGH profile should have 400 concurrent requests, got {config.concurrent_requests}"

        # Verify linear scaling with multiplier
        expected_concurrent = int(100 * config.load_multiplier)
        assert config.concurrent_requests == expected_concurrent, (
            f"Profile {profile}: Expected {expected_concurrent} concurrent requests, "
            f"got {config.concurrent_requests}"
        )

    def test_multiplier_based_formula_never_breaks(self):
        """Verify multiplier-based formula produces valid results for all profiles.

        This test ensures we never get unusably low iteration counts,
        which was the critical flaw in divisor-based formulas.
        """
        profiles = ["low", "medium", "high"]
        base_values = [5, 10, 12, 15, 18]  # Various base iteration counts from auth tests

        for profile in profiles:
            config = get_config_for_profile(profile)

            for base in base_values:
                # Use the same formula as the actual tests
                iterations = max(5, int(base * config.load_multiplier))

                # Critical validation: iterations must always be meaningful
                assert iterations >= 5, (
                    f"Profile {profile}, base {base}: Iterations too low ({iterations}). "
                    "Multiplier-based formula should prevent this!"
                )

                # Validate scaling relationship
                if profile == "low":
                    # LOW should never get more iterations than MEDIUM
                    medium_iterations = max(5, int(base * 1.0))
                    assert iterations <= medium_iterations, (
                        f"LOW profile has more iterations ({iterations}) than MEDIUM ({medium_iterations})"
                    )
                elif profile == "high":
                    # HIGH should always get more iterations than MEDIUM (unless capped at max)
                    medium_iterations = max(5, int(base * 1.0))
                    assert iterations >= medium_iterations, (
                        f"HIGH profile has fewer iterations ({iterations}) than MEDIUM ({medium_iterations})"
                    )

    def test_divisor_based_formula_would_fail(self):
        """Demonstrate why divisor-based formulas are broken.

        This test shows what would happen if we used the original
        divisor-based approach (concurrent_requests // divisor).
        """
        profiles = ["low", "medium", "high"]

        for profile in profiles:
            config = get_config_for_profile(profile)

            # Original flawed approach: divisor-based
            divisor = 40
            bad_iterations = config.concurrent_requests // divisor

            if profile == "low":
                # This is the critical failure case!
                # LOW profile: 50 // 40 = 1 iteration (useless!)
                assert bad_iterations == 1, (
                    f"LOW profile divisor-based formula should produce 1 iteration "
                    f"(demonstrating the flaw), got {bad_iterations}"
                )
            elif profile == "medium":
                # MEDIUM: 100 // 40 = 2 iterations (too low!)
                assert bad_iterations == 2, "MEDIUM profile divisor-based formula produces only 2 iterations"
            elif profile == "high":
                # HIGH: 400 // 40 = 10 iterations (this works, but others don't!)
                assert bad_iterations == 10, "HIGH profile divisor-based formula works, but LOW/MEDIUM fail"

            # Show that multiplier-based is always better
            good_iterations = max(5, int(10 * config.load_multiplier))
            assert good_iterations >= 5, f"Multiplier-based always produces meaningful iterations: {good_iterations}"

            # On LOW profile, multiplier-based is 5x better!
            if profile == "low":
                assert good_iterations == 5, "Multiplier-based: 5 iterations on LOW"
                assert bad_iterations == 1, "Divisor-based: 1 iteration on LOW"
                improvement = good_iterations / bad_iterations
                assert improvement == 5.0, f"Multiplier-based is {improvement}x better on LOW profile"
