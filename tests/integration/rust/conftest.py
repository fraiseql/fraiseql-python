"""Fixtures for Rust pipeline integration tests."""

import os

import pytest


@pytest.fixture(scope="session")
def rust_available():
    """Check if Rust extensions are available."""
    # Check environment variable
    if os.getenv("FRAISEQL_SKIP_RUST") == "1":
        return False

    # Try to import Rust extension
    try:
        import fraiseql_rust  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture
def rust_pipeline(rust_available):
    """Get Rust pipeline implementation if available."""
    if not rust_available:
        pytest.skip("Rust extensions not available")

    from fraiseql.rust import RustPipeline

    pipeline = RustPipeline()
    return pipeline


@pytest.fixture
def python_pipeline():
    """Get Python fallback pipeline for comparison tests."""
    from fraiseql.pipeline import PythonPipeline

    pipeline = PythonPipeline()
    return pipeline
