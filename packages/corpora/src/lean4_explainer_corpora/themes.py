"""Build a corpus theme: a palette for light and dark, type, and a few flourishes layered on the core stylesheet.

Themes use system fonts and inline `data:` images only, so pages still make no network requests.
"""

from __future__ import annotations

from collections.abc import Mapping

_VARS = ("fg", "bg", "muted", "line", "warn", "warn-bg", "accent", "panel")


def _block(palette: Mapping[str, str]) -> str:
    missing = [k for k in _VARS if k not in palette]
    if missing:
        raise ValueError(f"theme palette lacks {missing}")
    return " ".join(f"--{k}: {palette[k]};" for k in _VARS)


def make_theme(
    *,
    light: Mapping[str, str],
    dark: Mapping[str, str],
    body: str = "system-ui, sans-serif",
    heading: str = "",
    mono: str = "ui-monospace, SFMono-Regular, Consolas, monospace",
    extra: str = "",
) -> str:
    """CSS appended after the core stylesheet. `light` and `dark` each give every palette variable."""
    heading = heading or body
    return f"""
:root {{ {_block(light)} }}
@media (prefers-color-scheme: dark) {{ :root {{ {_block(dark)} }} }}
body {{ font-family: {body}; }}
h1, h2, .title {{ font-family: {heading}; }}
pre, code {{ font-family: {mono}; }}
a {{ text-decoration-color: var(--accent); text-underline-offset: 0.18em; }}
a:hover {{ color: var(--accent); }}
pre {{ background: var(--panel); }}
h2 {{ border-bottom-color: var(--accent); }}
input[type="search"]:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
.kind, ol.decls > li > b:first-child {{ color: var(--accent); }}
{extra}
""".lstrip()


def svg(markup: str) -> str:
    """An inline SVG as a CSS url() value."""
    from urllib.parse import quote

    return f'url("data:image/svg+xml,{quote(markup, safe="/:=,;()")}")'
