"""
Common test configuration for FraiseQL.
"""


def pytest_configure(config) -> None:
    """Configure common test markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "database: Tests requiring database")
    config.addinivalue_line("markers", "slow: Slow-running tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "security: Security-related tests")
    config.addinivalue_line("markers", "auth: Authentication tests")
    config.addinivalue_line("markers", "blog_demo: Blog demo tests (blueprints)")
    config.addinivalue_line("markers", "blog_demo_simple: Simple blog demo tests")
    config.addinivalue_line("markers", "blog_demo_enterprise: Enterprise blog demo tests")
