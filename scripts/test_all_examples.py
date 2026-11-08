#!/usr/bin/env python3
"""
Test harness for all FraiseQL examples

This script validates that all example applications work correctly by:
1. Checking file structure
2. Running basic validation tests
3. Generating a pass/fail report

Usage:
    python scripts/test_all_examples.py
    python scripts/test_all_examples.py --example blog_simple
    python scripts/test_all_examples.py --report-only
"""

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

# Example configurations
EXAMPLES = {
    "blog_simple": {
        "path": "examples/blog_simple",
        "required_files": [
            "README.md",
            "app.py",
            "models.py",
            "requirements.txt",
            "db/setup.sql",
        ],
        "optional_files": [
            "docker-compose.yml",
            "Dockerfile",
            "pytest.ini",
        ],
        "validation": "python_syntax",
    },
    "rag-system": {
        "path": "examples/rag-system",
        "required_files": [
            "README.md",
            "app.py",
            "schema.sql",
            "requirements.txt",
            ".env.example",
        ],
        "optional_files": [
            "docker-compose.yml",
            "Dockerfile",
            "test-rag-system.sh",
        ],
        "validation": "python_syntax",
    },
}


@dataclass
class TestResult:
    """Test result for an example"""

    example_name: str
    passed: bool
    checks_passed: int = 0
    checks_total: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class ExampleTester:
    """Test harness for FraiseQL examples"""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.results: list[TestResult] = []

    def test_file_structure(self, example_name: str, config: dict) -> TestResult:
        """Test that example has required files"""
        result = TestResult(example_name=example_name, passed=True)
        example_path = self.repo_root / config["path"]

        print(f"\n{'='*60}")
        print(f"Testing: {example_name}")
        print(f"Path: {example_path}")
        print(f"{'='*60}")

        # Check example directory exists
        if not example_path.exists():
            result.errors.append(f"Example directory not found: {example_path}")
            result.passed = False
            return result

        # Check required files
        print("\n📋 Checking required files...")
        for file_path in config["required_files"]:
            full_path = example_path / file_path
            result.checks_total += 1

            if full_path.exists():
                print(f"  ✅ {file_path}")
                result.checks_passed += 1
            else:
                print(f"  ❌ {file_path} - MISSING")
                result.errors.append(f"Required file missing: {file_path}")
                result.passed = False

        # Check optional files (warnings only)
        print("\n📄 Checking optional files...")
        for file_path in config["optional_files"]:
            full_path = example_path / file_path
            if full_path.exists():
                print(f"  ✅ {file_path}")
            else:
                print(f"  ⚠️  {file_path} - not present (optional)")
                result.warnings.append(f"Optional file missing: {file_path}")

        return result

    def validate_python_syntax(
        self, example_name: str, config: dict
    ) -> TestResult:
        """Validate Python file syntax"""
        result = TestResult(example_name=example_name, passed=True)
        example_path = self.repo_root / config["path"]

        print("\n🐍 Validating Python syntax...")

        # Find all Python files
        python_files = list(example_path.rglob("*.py"))

        for py_file in python_files:
            # Skip __pycache__ and other generated files
            if "__pycache__" in str(py_file) or ".pytest_cache" in str(py_file):
                continue

            result.checks_total += 1
            relative_path = py_file.relative_to(example_path)

            try:
                # Check syntax using py_compile
                import py_compile

                py_compile.compile(str(py_file), doraise=True)
                print(f"  ✅ {relative_path}")
                result.checks_passed += 1
            except py_compile.PyCompileError as e:
                print(f"  ❌ {relative_path} - Syntax error")
                result.errors.append(f"Syntax error in {relative_path}: {e}")
                result.passed = False

        return result

    def check_requirements(self, example_name: str, config: dict) -> TestResult:
        """Check that requirements.txt is valid"""
        result = TestResult(example_name=example_name, passed=True)
        example_path = self.repo_root / config["path"]
        req_file = example_path / "requirements.txt"

        print("\n📦 Checking requirements.txt...")

        if not req_file.exists():
            result.warnings.append("requirements.txt not found (skipping)")
            return result

        result.checks_total += 1

        try:
            with open(req_file) as f:
                lines = f.readlines()

            # Basic validation: check for common issues
            issues = []
            for i, line in enumerate(lines, 1):
                line = line.strip()

                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                # Check for basic package name validity
                if " " in line and "==" not in line and ">=" not in line:
                    issues.append(f"Line {i}: Suspicious spacing in '{line}'")

            if issues:
                for issue in issues:
                    print(f"  ⚠️  {issue}")
                    result.warnings.append(issue)
            else:
                print(f"  ✅ requirements.txt is valid")
                result.checks_passed += 1

        except Exception as e:
            result.errors.append(f"Failed to parse requirements.txt: {e}")
            result.passed = False

        return result

    def check_readme(self, example_name: str, config: dict) -> TestResult:
        """Check README quality"""
        result = TestResult(example_name=example_name, passed=True)
        example_path = self.repo_root / config["path"]
        readme_file = example_path / "README.md"

        print("\n📖 Checking README.md...")

        if not readme_file.exists():
            result.errors.append("README.md not found")
            result.passed = False
            return result

        result.checks_total += 1

        try:
            with open(readme_file) as f:
                content = f.read()

            # Check for essential sections
            essential_sections = [
                "##",  # Has some sections
                "Quick Start" or "Getting Started" or "Setup",
            ]

            warnings = []

            # Check file is not empty
            if len(content.strip()) < 100:
                warnings.append("README is very short (< 100 chars)")

            # Check for code blocks
            if "```" not in content:
                warnings.append("No code blocks found in README")

            # Check for links
            if not ("http://" in content or "https://" in content or "](" in content):
                warnings.append("No links found in README")

            if warnings:
                for warning in warnings:
                    print(f"  ⚠️  {warning}")
                    result.warnings.extend(warnings)
            else:
                print(f"  ✅ README.md looks good")
                result.checks_passed += 1

        except Exception as e:
            result.errors.append(f"Failed to read README.md: {e}")
            result.passed = False

        return result

    def test_example(self, example_name: str) -> TestResult:
        """Run all tests for an example"""
        config = EXAMPLES[example_name]

        # Run all test categories
        file_result = self.test_file_structure(example_name, config)
        syntax_result = self.validate_python_syntax(example_name, config)
        req_result = self.check_requirements(example_name, config)
        readme_result = self.check_readme(example_name, config)

        # Combine results
        combined = TestResult(
            example_name=example_name,
            passed=(
                file_result.passed
                and syntax_result.passed
                and req_result.passed
                and readme_result.passed
            ),
            checks_passed=(
                file_result.checks_passed
                + syntax_result.checks_passed
                + req_result.checks_passed
                + readme_result.checks_passed
            ),
            checks_total=(
                file_result.checks_total
                + syntax_result.checks_total
                + req_result.checks_total
                + readme_result.checks_total
            ),
            errors=(
                file_result.errors
                + syntax_result.errors
                + req_result.errors
                + readme_result.errors
            ),
            warnings=(
                file_result.warnings
                + syntax_result.warnings
                + req_result.warnings
                + readme_result.warnings
            ),
        )

        # Print summary for this example
        print(f"\n{'─'*60}")
        if combined.passed:
            print(
                f"✅ {example_name}: PASSED ({combined.checks_passed}/{combined.checks_total} checks)"
            )
        else:
            print(
                f"❌ {example_name}: FAILED ({combined.checks_passed}/{combined.checks_total} checks)"
            )

        if combined.errors:
            print(f"\nErrors ({len(combined.errors)}):")
            for error in combined.errors:
                print(f"  - {error}")

        if combined.warnings:
            print(f"\nWarnings ({len(combined.warnings)}):")
            for warning in combined.warnings:
                print(f"  - {warning}")

        self.results.append(combined)
        return combined

    def generate_report(self, output_file: Path | None = None) -> str:
        """Generate test report"""
        total_passed = sum(1 for r in self.results if r.passed)
        total_failed = len(self.results) - total_passed

        report = []
        report.append("=" * 80)
        report.append("FraiseQL Examples - Test Report")
        report.append("=" * 80)
        report.append(f"Generated: {datetime.utcnow().isoformat()}")
        report.append(f"Total Examples: {len(self.results)}")
        report.append(f"Passed: {total_passed}")
        report.append(f"Failed: {total_failed}")
        report.append("")

        # Summary table
        report.append("Summary:")
        report.append("-" * 80)
        for result in self.results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            report.append(
                f"  {status}  {result.example_name:20s}  "
                f"({result.checks_passed}/{result.checks_total} checks)"
            )

        report.append("")

        # Detailed results
        for result in self.results:
            report.append("=" * 80)
            report.append(f"Example: {result.example_name}")
            report.append("=" * 80)
            report.append(f"Status: {'PASSED' if result.passed else 'FAILED'}")
            report.append(
                f"Checks: {result.checks_passed}/{result.checks_total} passed"
            )
            report.append("")

            if result.errors:
                report.append(f"Errors ({len(result.errors)}):")
                for error in result.errors:
                    report.append(f"  - {error}")
                report.append("")

            if result.warnings:
                report.append(f"Warnings ({len(result.warnings)}):")
                for warning in result.warnings:
                    report.append(f"  - {warning}")
                report.append("")

        report_text = "\n".join(report)

        # Save to file if requested
        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(report_text)
            print(f"\n📄 Report saved to: {output_file}")

        return report_text


def main():
    parser = argparse.ArgumentParser(description="Test FraiseQL examples")
    parser.add_argument(
        "--example", choices=list(EXAMPLES.keys()), help="Test specific example only"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Save report to file (default: .phases/docs-review/example_test_report.txt)",
    )
    parser.add_argument(
        "--json", type=Path, help="Save JSON report to file"
    )
    args = parser.parse_args()

    # Find repository root
    repo_root = Path(__file__).parent.parent

    # Create tester
    tester = ExampleTester(repo_root)

    # Test examples
    if args.example:
        examples_to_test = [args.example]
    else:
        examples_to_test = list(EXAMPLES.keys())

    print(f"🧪 Testing {len(examples_to_test)} example(s)...\n")

    for example in examples_to_test:
        tester.test_example(example)

    # Generate report
    print("\n" + "=" * 80)
    print("FINAL REPORT")
    print("=" * 80)

    report_path = args.report or (
        repo_root / ".phases/docs-review/example_test_report.txt"
    )
    report = tester.generate_report(output_file=report_path)
    print(report)

    # Generate JSON report if requested
    if args.json:
        json_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "total": len(tester.results),
            "passed": sum(1 for r in tester.results if r.passed),
            "failed": sum(1 for r in tester.results if not r.passed),
            "results": [
                {
                    "example": r.example_name,
                    "passed": r.passed,
                    "checks_passed": r.checks_passed,
                    "checks_total": r.checks_total,
                    "errors": r.errors,
                    "warnings": r.warnings,
                }
                for r in tester.results
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(json_data, indent=2))
        print(f"📊 JSON report saved to: {args.json}")

    # Exit with error code if any tests failed
    all_passed = all(r.passed for r in tester.results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
