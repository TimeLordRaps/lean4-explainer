"""Prefix-sharded declaration index written as script files, so search also works from file://."""

from __future__ import annotations

import json
import string
from collections.abc import Callable, Mapping
from urllib.parse import quote

_SAFE = frozenset(string.ascii_lowercase + string.digits)


def shard_key(name: str) -> str:
    head = name.lower()[:2]
    return "".join(ch if ch in _SAFE else "_" for ch in head).ljust(2, "_")


def _url(rel: str) -> str:
    return "/".join(quote(part) for part in rel.split("/")) + ".html"


def write_search(
    locations: Mapping[str, tuple[str, int]],
    write: Callable[[tuple[str, ...], str], int],
) -> tuple[int, int]:
    file_index: dict[str, int] = {}
    urls: list[str] = []
    shards: dict[str, list[list[object]]] = {}
    for name in sorted(locations):
        rel, line = locations[name]
        index = file_index.get(rel)
        if index is None:
            index = file_index[rel] = len(urls)
            urls.append(_url(rel))
        shards.setdefault(shard_key(name), []).append([name, index, line])

    written = write(
        ("_assets", "search", "files.js"),
        "window.L4F = " + json.dumps(urls, ensure_ascii=False) + ";\n",
    )
    entries = 0
    for key in sorted(shards):
        rows = shards[key]
        entries += len(rows)
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        written += write(
            ("_assets", "search", f"s_{key}.js"),
            f"window.l4shard({json.dumps(key)}, {payload});\n",
        )
    return entries, written
