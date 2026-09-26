"""Content-addressed versioning for the no-build-step dashboard static files.

The dashboard ships as plain HTML/CSS/JS with no build step, so file URLs
never change between releases. Behind a cache (browser or Cloudflare), that
lets a new ``index.html`` be paired with a stale ``app.js`` after a deploy.
The fix: hash the whole static directory into a build id, serve every asset
under a URL that embeds it, and rewrite ``index.html``'s references to match
at startup. A stale ``index.html`` can then never point at the wrong assets,
because there's only ever one build id in flight per process.
"""

import hashlib
from pathlib import Path


def compute_build_id(static_dir: Path) -> str:
    """Hash every file under ``static_dir`` into a short, stable build id.

    The hash covers sorted relative paths plus file contents, so it changes
    whenever any file is added, removed, or edited, and is independent of
    filesystem iteration order.
    """
    hasher = hashlib.sha256()
    relative_paths = sorted(
        path.relative_to(static_dir).as_posix() for path in static_dir.rglob("*") if path.is_file()
    )
    for relative_path in relative_paths:
        hasher.update(relative_path.encode("utf-8"))
        hasher.update((static_dir / relative_path).read_bytes())
    return hasher.hexdigest()[:12]


def _replace_exactly_once(html: str, old: str, new: str) -> str:
    count = html.count(old)
    if count != 1:
        raise ValueError(
            f"expected exactly one occurrence of {old!r} in index.html, found {count}; "
            "static asset versioning cannot rewrite it safely"
        )
    return html.replace(old, new, 1)


def rewrite_index_html(html: str, build_id: str) -> str:
    """Rewrite ``index.html``'s asset references to the versioned static path.

    Only the ``app.css`` stylesheet link and ``app.js`` module script are
    rewritten; ``<a href="#/...">`` navigation links are untouched. Raises
    ``ValueError`` if either reference isn't found exactly once, so a future
    edit to ``index.html`` fails loudly at startup instead of silently
    breaking versioning.
    """
    prefix = f"/static/{build_id}/"
    html = _replace_exactly_once(html, 'href="app.css"', f'href="{prefix}app.css"')
    html = _replace_exactly_once(html, 'src="app.js"', f'src="{prefix}app.js"')
    return html
