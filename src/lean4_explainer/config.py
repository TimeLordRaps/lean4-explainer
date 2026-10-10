"""Settings from lean4-explainer.toml. Unknown keys and wrong types are errors."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ExplainerError

PAGES_LIMIT_BYTES = 1_000_000_000


@dataclass(frozen=True)
class Config:
    title: str = "Lean proofsite"
    exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    source_url: str | None = None
    source_ref: str = "main"
    search: bool = True
    cross_links: bool = True
    learning_path: bool = True
    byte_budget: int = PAGES_LIMIT_BYTES
    source_links: str = "declaration"  # "declaration": one link per declaration; "file": one per page
    home: str | None = None  # relative URL of a landing page above this site, when it is one of several


_TYPES: dict[str, type] = {
    "title": str,
    "exclude": list,
    "include": list,
    "source_url": str,
    "source_ref": str,
    "search": bool,
    "cross_links": bool,
    "learning_path": bool,
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
    unknown = sorted(set(data) - set(_TYPES))
    if unknown:
        raise ExplainerError(f"unknown config keys in {path}: {', '.join(unknown)}")
    values: dict[str, object] = {}
    for key, value in data.items():
        if type(value) is not _TYPES[key]:
            raise ExplainerError(f"config key '{key}' must be {_TYPES[key].__name__} in {path}")
        if key in ("exclude", "include"):
            if not all(isinstance(item, str) for item in value):
                raise ExplainerError(f"'{key}' must be a list of strings in {path}")
            value = tuple(value)
        if key == "source_links" and value not in ("declaration", "file"):
            raise ExplainerError(f"'source_links' must be \"declaration\" or \"file\" in {path}")
        values[key] = value
    return Config(**values)
