"""mkdocs hook: render D2 diagram fences to SVG at build time.

D2 fences in markdown are written as:

    ```d2
    direction: right
    A -> B -> C
    ```

During `mkdocs build` (and `mkdocs serve`), each fence is passed to the
`d2` binary via stdin and the resulting SVG is inlined into the page.

If `d2` is not installed the fence degrades gracefully to a code block —
no hard failure, so contributors without D2 can still build docs locally.
"""

from __future__ import annotations

import html
import re
import subprocess

# Matches the HTML that pymdownx.superfences emits for a custom fence with
# class="d2":  <pre class="d2"><code>…</code></pre>
# The inner <code> tag may carry additional attributes.
_D2_BLOCK = re.compile(
    r'<pre[^>]*\bclass="[^"]*\bd2\b[^"]*"[^>]*>'
    r"<code[^>]*>(.*?)</code></pre>",
    re.DOTALL,
)


def _render(source: str) -> str | None:
    """Pass D2 source to the d2 binary via stdin, return SVG or None."""
    try:
        proc = subprocess.run(
            ["d2", "-", "-"],
            input=source,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    except FileNotFoundError:
        # d2 not installed — degrade silently
        pass
    except subprocess.TimeoutExpired:
        pass
    return None


def on_page_content(html_content: str, **_kwargs: object) -> str:  # noqa: ARG001
    """Replace d2 fence blocks with rendered SVG inline."""

    def replace(match: re.Match[str]) -> str:
        source = html.unescape(match.group(1))
        svg = _render(source)
        if svg:
            return f'<div class="d2-diagram">{svg}</div>'
        return match.group(0)  # graceful fallback: keep code block

    return _D2_BLOCK.sub(replace, html_content)
