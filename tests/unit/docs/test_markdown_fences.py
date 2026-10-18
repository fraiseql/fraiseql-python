"""Code fences in docs/, examples/ and README.md must be balanced.

An unclosed fence, or a closer written with an info string (```` ```text ````),
turns the rest of the page, or the next code block, into code.

Scanned: the git-tracked ``docs/**.md``, ``examples/**.md`` and ``README.md``.
Not scanned: ``docs/archive/`` and anything outside those paths (``.claude/``,
``dev/``).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXCLUDED_PREFIXES = ("docs/archive/",)

# CommonMark: up to 3 spaces of indent, then 3+ backticks or tildes.
_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_INFO_WORD = re.compile(r"[\w+-]+")


def find_fence_problems(text: str) -> list[str]:
    """Return the fence problems in a Markdown text, one message per problem.

    A closer uses the opener's character, is at least as long, and has no info
    string. A fence with an info string while a block is open (and at least as
    long as its opener) is reported: it was meant to open a block, so the
    previous one was never closed.
    """
    problems = []
    open_fence: tuple[str, int, int] | None = None  # (char, length, line)
    for lineno, line in enumerate(text.splitlines(), 1):
        match = _FENCE.match(line)
        if not match:
            continue
        char, length, rest = match.group(2)[0], len(match.group(2)), match.group(3).strip()
        if open_fence is None:
            if char == "`" and "`" in rest:
                continue  # inline code, not a fence
            open_fence = (char, length, lineno)
            continue
        open_char, open_length, open_line = open_fence
        if char != open_char or length < open_length:
            continue  # content of the open block
        if not rest:
            open_fence = None
        elif _INFO_WORD.fullmatch(rest):
            problems.append(
                f"line {lineno}: fence {match.group(2)}{rest} inside the block opened at "
                f"line {open_line}"
            )
    if open_fence is not None:
        problems.append(f"line {open_fence[2]}: fence never closed")
    return problems


def _scanned_files() -> list[str]:
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        return []
    out = subprocess.run(
        ["git", "ls-files", "docs/**.md", "examples/**.md", "README.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.splitlines() if p and not p.startswith(EXCLUDED_PREFIXES)]


_FILES = _scanned_files()


def test_balanced_fences_pass() -> None:
    text = "intro\n```python\nx = 1\n```\n\n````markdown\n```sql\nSELECT 1;\n```\n````\n"
    assert find_fence_problems(text) == []


def test_unclosed_fence_is_reported() -> None:
    assert find_fence_problems("```python\nx = 1\n") == ["line 1: fence never closed"]


def test_closer_with_info_string_is_reported() -> None:
    text = "```graphql\n{ a }\n```text\nprose\n```\n"
    assert find_fence_problems(text) == [
        "line 3: fence ```text inside the block opened at line 1",
    ]


@pytest.mark.skipif(not _FILES, reason="needs a git checkout to list the docs")
@pytest.mark.parametrize("path", _FILES)
def test_markdown_fences_are_balanced(path: str) -> None:
    text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
    assert find_fence_problems(text) == []
