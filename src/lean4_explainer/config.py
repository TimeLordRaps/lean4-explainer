"""Settings from lean4-explainer.toml. Unknown keys and wrong types are errors."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ExplainerError
from .extensions import config_keys

PAGES_LIMIT_BYTES = 1_000_000_000


@dataclass(frozen=True)
class Config:
    title: str = "Lean proofsite"
    exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    extra_kinds: tuple[str, ...] = ()  # more declaration keywords to list, such as a project's `problem`
    source_url: str | None = None
    source_ref: str = "main"
    search: bool = True
    cross_links: bool = True
    byte_budget: int = PAGES_LIMIT_BYTES
    source_links: str = "declaration"  # "declaration": one link per declaration; "file": one per page
    home: str | None = None  # relative URL of a landing page above this site, when it is one of several
    options: tuple[tuple[str, object], ...] = ()  # keys that installed extensions declared, sorted


_TYPES: dict[str, type] = {
    "title": str,
    "exclude": list,
    "include": list,
    "extra_kinds": list,
    "source_url": str,
    "source_ref": str,
    "search": bool,
    "cross_links": bool,
    "byte_budget": int,
    "source_links": str,
    "home": str,
}


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    if not path.is_file():
        raise ExplainerError(f"config file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ExplainerError(f"invalid TOML in {path}: {exc}") from exc
    allowed = {**config_keys(), **_TYPES}
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ExplainerError(f"unknown config keys in {path}: {', '.join(unknown)}")
    values: dict[str, object] = {}
    options: dict[str, object] = {}
    for key, value in data.items():
        if type(value) is not allowed[key]:
            raise ExplainerError(f"config key '{key}' must be {allowed[key].__name__} in {path}")
        if key not in _TYPES:
            options[key] = value
            continue
        if key in ("exclude", "include", "extra_kinds"):
            if not all(isinstance(item, str) for item in value):
                raise ExplainerError(f"'{key}' must be a list of strings in {path}")
            value = tuple(value)
        if key == "extra_kinds" and not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", kind) for kind in value):
            raise ExplainerError(f"'extra_kinds' entries must be plain keywords in {path}")
        if key == "source_links" and value not in ("declaration", "file"):
            raise ExplainerError(f"'source_links' must be \"declaration\" or \"file\" in {path}")
        values[key] = value
    return Config(**values, options=tuple(sorted(options.items())))
