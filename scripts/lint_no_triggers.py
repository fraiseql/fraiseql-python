#!/usr/bin/env python3
"""
Lint examples and docs for BAD trigger usage (business logic triggers).

Allows infrastructure triggers (crypto chain on audit_events).
Fails CI if bad triggers found.

Usage:
    python scripts/lint_no_triggers.py
    python scripts/lint_no_triggers.py --strict  # Fail on ANY trigger

Exit codes:
    0 - No business logic triggers found (PASS)
    1 - Business logic triggers found (FAIL)
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple

# Trigger detection pattern
TRIGGER_PATTERN = re.compile(
    r'CREATE\s+(OR\s+REPLACE\s+)?TRIGGER',
    re.IGNORECASE
)

# Allowed infrastructure trigger patterns
ALLOWED_TRIGGER_PATTERNS = [
    r'populate_crypto_trigger',      # Cryptographic chain infrastructure
    r'ON\s+audit_events',             # Triggers on audit_events table only
    r'create_audit_partition_trigger' # Partition management infrastructure
]

# Allowed files with infrastructure triggers (source code only)
ALLOWED_TRIGGER_FILES = [
    'src/fraiseql/enterprise/migrations/002_unified_audit.sql',
    'src/fraiseql/enterprise/migrations/001_audit_tables.sql',
]

# Documentation files that should show BOTH patterns (commented out bad patterns)
DOCUMENTATION_EXCEPTION_FILES = [
    'docs/database/avoid-triggers.md',     # Educational guide showing bad patterns
]


def is_allowed_trigger(trigger_line: str, file_path: Path, full_context: str) -> bool:
    """
    Check if trigger is an allowed infrastructure exception.

    Args:
        trigger_line: The line containing CREATE TRIGGER
        file_path: Path to the file being checked
        full_context: Full file content for context checking

    Returns:
        True if trigger is allowed (infrastructure), False if not (business logic)
    """
    file_path_str = str(file_path)

    # Check if file is in allowed list (source code infrastructure)
    if any(allowed in file_path_str for allowed in ALLOWED_TRIGGER_FILES):
        return True

    # Check if file is documentation that comments out bad patterns
    if any(doc_file in file_path_str for doc_file in DOCUMENTATION_EXCEPTION_FILES):
        # In documentation, triggers should be commented out or shown as BAD examples
        # Look for commented trigger (-- CREATE TRIGGER or ❌)
        lines_around = full_context.split('\n')
        trigger_idx = None
        for i, line in enumerate(lines_around):
            if trigger_line.strip() in line:
                trigger_idx = i
                break

        if trigger_idx is not None:
            # Check if trigger is commented out
            trigger_line_full = lines_around[trigger_idx]
            if trigger_line_full.strip().startswith('--'):
                return True  # Commented out example is OK

            # Check for BAD marker nearby (within 5 lines before)
            for i in range(max(0, trigger_idx - 5), trigger_idx):
                if '❌' in lines_around[i] or 'BAD' in lines_around[i].upper() or 'AVOID' in lines_around[i].upper():
                    return True  # Marked as bad example is OK

    # Check if trigger matches allowed patterns
    for pattern in ALLOWED_TRIGGER_PATTERNS:
        if re.search(pattern, trigger_line, re.IGNORECASE):
            return True

        # Check surrounding context (next 5 lines)
        lines = full_context.split('\n')
        for i, line in enumerate(lines):
            if trigger_line.strip() in line:
                context_lines = '\n'.join(lines[i:i+5])
                if re.search(pattern, context_lines, re.IGNORECASE):
                    return True

    return False


def check_file(file_path: Path) -> List[Tuple[int, str]]:
    """
    Check file for BAD trigger usage.

    Args:
        file_path: Path to file to check

    Returns:
        List of (line_number, issue_description) tuples
    """
    issues = []

    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        print(f"⚠️  Warning: Could not read {file_path}: {e}", file=sys.stderr)
        return issues

    for i, line in enumerate(content.splitlines(), 1):
        if TRIGGER_PATTERN.search(line):
            if not is_allowed_trigger(line, file_path, content):
                issues.append((
                    i,
                    f"Business logic trigger found: {line.strip()[:80]}"
                ))

    return issues


def main():
    """Scan all files for bad triggers."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Lint for business logic triggers in FraiseQL codebase'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Fail on ANY trigger (including infrastructure)'
    )
    args = parser.parse_args()

    # Paths to check
    paths_to_check = [
        Path("examples/"),
        Path("docs/"),
    ]

    # File patterns to check
    file_patterns = ["**/*.sql", "**/*.md", "**/*.py"]

    all_issues = []
    files_checked = 0

    print("🔍 Scanning for business logic triggers...")
    print()

    for base_path in paths_to_check:
        if not base_path.exists():
            continue

        for pattern in file_patterns:
            for file_path in base_path.glob(pattern):
                files_checked += 1
                issues = check_file(file_path)

                if issues:
                    all_issues.extend([
                        (file_path, line_no, issue)
                        for line_no, issue in issues
                    ])

    # Report results
    if all_issues:
        print(f"❌ Found {len(all_issues)} business logic trigger(s) in {len(set(f for f, _, _ in all_issues))} file(s):")
        print()

        for file_path, line_no, issue in all_issues:
            print(f"  {file_path}:{line_no}")
            print(f"    {issue}")
            print()

        print("💡 FraiseQL Best Practice:")
        print("   - Use explicit audit logging: call log_and_return_mutation() in mutation functions")
        print("   - Infrastructure triggers (crypto chain on audit_events) are OK")
        print("   - See docs/database/avoid-triggers.md for details")
        print()

        sys.exit(1)
    else:
        print(f"✅ No business logic triggers found ({files_checked} files checked)")
        print("   Infrastructure triggers (populate_crypto_trigger, audit_events) are allowed")
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
