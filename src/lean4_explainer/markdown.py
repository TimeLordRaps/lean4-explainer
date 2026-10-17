r"""Doc comments as HTML. Lean doc comments are Markdown with TeX in them, as doc-gen4 shows them. This draws the
part people use: paragraphs, headings, lists, quotes, rules, fenced code, `code`, *emphasis*, **strong**, links and
bare URLs. `$…$`, `$$…$$`, `\(…\)` and `\[…\]` stay as written, inside <span class="tex">, for an extension (the
reader) to typeset.

Everything is escaped. A link is made only to an http, https or mailto URL, or to a relative one.

Dollars: a formula may run over a line break but not a blank line; a `$` inside braces (`\\text{$m$ prime}`) does not
close it; a `$` just before a digit does not close it ("$100 for a proof and $1000 for a disproof" is text). Pandoc
also wants no space just inside the dollars; doc-gen4 does not, so a formula with a space there counts when it looks
like TeX (a backslash, ^, _, =, braces or a math symbol), and "I have $ and you have $" stays text."""

from __future__ import annotations

import re
from html import escape, unescape

__all__ = ["doc_html", "inline_html", "math_spans"]

_OPEN, _CLOSE = "", ""  # around a placeholder's number while inline markup is matched
_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_TEXISH = re.compile(r"[\\^_={}]|[Ͱ-Ͽ℀-⅏←-⋿⟀-⟯⦀-⫿]|^\s*[A-Za-z]\s*$")
_BLANK = re.compile(r"\n[ \t]*(?:\n|$)")

_FENCE = re.compile(r"^([ \t]{0,3})(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^[ \t]{0,3}(=+|-+)[ \t]*$")
_RULE = re.compile(r"^[ \t]{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
_ITEM = re.compile(r"^([ \t]*)([-*+]|(\d{1,9})[.)])(?:([ \t]+)(.*)|[ \t]*$)")
_QUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?(.*)$")

_LINK = re.compile(r"\[([^\]]+)\]\(\s*((?:[^()\s]|\([^()\s]*\))+)\s*\)")  # text may run over a line break
_AUTOLINK = re.compile(r"&lt;((?:https?|mailto):[^\s]+?)&gt;")
_BARE = re.compile(r"(?<![\w/=\"'])(?:https?://)(?:(?!&(?:lt|gt|quot|#x27);)[^\s])+")
_STRONG = re.compile(r"(?<!\*)\*\*(?=[^\s*])(.+?)(?<=[^\s*])\*\*(?!\*)|(?<![\w_])__(?=[^\s_])(.+?)(?<=[^\s_])__(?![\w_])", re.S)
_EM = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])|(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", re.S)
_PLACEHOLDER = re.compile("(\\d+)")


# ---- inline -------------------------------------------------------------------------------------------------------

def math_spans(text: str) -> list[tuple[int, int]]:
    """Where the formulas are: (start, end), including their dollar or backslash delimiters."""
    return [(start, end) for kind, start, end in _scan(text) if kind == "tex"]


def _scan(s: str) -> list[tuple[str, int, int]]:
    """The code spans, formulas and backslash escapes of a paragraph, in order: (kind, start, end)."""
    found: list[tuple[str, int, int]] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in "([":
            end = _backslash_math_end(s, i)
            if end is None:
                found.append(("escape", i, i + 2))
                i += 2
            else:
                found.append(("tex", i, end))
                i = end
        elif c == "\\" and i + 1 < n and s[i + 1] in _PUNCT:
            found.append(("escape", i, i + 2))
            i += 2
        elif c == "`":
            run = 0
            while i + run < n and s[i + run] == "`":
                run += 1
            end = _code_end(s, i, run)
            if end is None:
                i += run  # a lone run of backticks is text
            else:
                found.append(("code", i, end))
                i = end
        elif c == "$":
            end = _math_end(s, i)
            if end is None:
                i += 1
            else:
                found.append(("tex", i, end))
                i = end
        else:
            i += 1
    return found


def _backslash_math_end(s: str, i: int) -> int | None:
    r"""End of a LaTeX ``\(...\)`` or ``\[...\]`` formula, or None when it is unclosed/empty."""
    close = "\\)" if s[i + 1] == "(" else "\\]"
    end = s.find(close, i + 2)
    if end < 0:
        return None
    body = s[i + 2 : end]
    if not body.strip() or _BLANK.search(body):
        return None
    return end + 2


def _code_end(s: str, i: int, run: int) -> int | None:
    j = i + run
    while True:
        j = s.find("`" * run, j)
        if j < 0:
            return None
        k = j + run
        if k < len(s) and s[k] == "`":  # a longer run does not close this one
            while k < len(s) and s[k] == "`":
                k += 1
            j = k
            continue
        return k


def _math_end(s: str, i: int) -> int | None:
    display = s.startswith("$$", i)
    j = i + (2 if display else 1)
    n, depth = len(s), 0
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "\n" and _BLANK.match(s, j):
            return None  # a formula does not run over a blank line
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(depth - 1, 0)
        elif c == "$" and depth == 0:
            if display:
                if s.startswith("$$", j):
                    return j + 2 if s[i + 2 : j].strip() else None
            elif not (j + 1 < n and s[j + 1].isdigit()):  # "$5" opens nothing and closes nothing
                body = s[i + 1 : j]
                if not body.strip():
                    return None
                if (body[0].isspace() or body[-1].isspace()) and not _TEXISH.search(body):
                    return None
                return j + 1
        j += 1
    return None


def inline_html(text: str) -> str:
    """One paragraph's inline Markdown as HTML."""
    text = text.replace(_OPEN, "�").replace(_CLOSE, "�")
    held: list[str] = []

    def hold(html: str) -> str:
        held.append(html)
        return f"{_OPEN}{len(held) - 1}{_CLOSE}"

    pieces, last = [], 0
    for kind, start, end in _scan(text):
        pieces.append(escape(text[last:start], quote=False))
        if kind == "escape":
            pieces.append(hold(escape(text[start + 1], quote=False)))
        elif kind == "code":
            body = text[start:end].strip("`").replace("\n", " ")
            if len(body) > 2 and body[0] == " " and body[-1] == " " and body.strip():
                body = body[1:-1]
            pieces.append(hold(f"<code>{escape(body, quote=False)}</code>"))
        else:
            pieces.append(hold(f'<span class="tex">{escape(text[start:end], quote=False)}</span>'))
        last = end
    pieces.append(escape(text[last:], quote=False))
    html = "".join(pieces)

    def link(match: re.Match[str]) -> str:
        url = _safe_url(match.group(2))
        if url is None or _OPEN in match.group(2):
            return match.group(0)
        return hold(f'<a href="{url}">') + match.group(1) + hold("</a>")

    def bare(url: str) -> str:
        """A URL written out in the text, without the punctuation that ends its sentence."""
        tail = ""
        while url and (
            url[-1] in ".,;:!?"
            or (url[-1] == ")" and url.count("(") < url.count(")"))
            or (url[-1] == "]" and url.count("[") < url.count("]"))
        ):
            tail = url[-1] + tail
            url = url[:-1]
        safe = _safe_url(url)
        return (hold(f'<a href="{safe}">{url}</a>') if safe else url) + tail

    html = _AUTOLINK.sub(lambda m: hold(f'<a href="{safe}">{m.group(1)}</a>') if (safe := _safe_url(m.group(1))) else m.group(0), html)
    html = _LINK.sub(link, html)
    html = _BARE.sub(lambda m: bare(m.group(0)), html)
    html = _STRONG.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", html)
    html = _EM.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", html)
    while _OPEN in html:  # a held piece can hold others (a link's text)
        html = _PLACEHOLDER.sub(lambda m: held[int(m.group(1))], html)
    return html


def _safe_url(escaped: str) -> str | None:
    """The URL for an href, or None when it is not one to follow (javascript:, data:, …)."""
    raw = unescape(escaped).strip()
    if raw.startswith("&lt;") or raw.startswith("<"):
        raw = raw.strip("<>")
    scheme = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", raw)
    if scheme and scheme.group(1).lower() not in ("http", "https", "mailto"):
        return None
    if any(ch in raw for ch in "\n\r\t "):
        return None
    return escape(raw, quote=True)


# ---- blocks -------------------------------------------------------------------------------------------------------

def doc_html(text: str) -> str:
    """A doc comment as HTML blocks."""
    return "".join(_blocks(text.replace("\r\n", "\n").split("\n")))


def _starts_block(line: str) -> bool:
    return any(rule.match(line) for rule in (_ITEM, _HEADING, _QUOTE, _RULE, _FENCE, _SETEXT))


def _open_display(text: str) -> bool:
    """Whether a `$$` formula is still open at the end of `text`: its next line belongs to it."""
    covered = [(start, end) for kind, start, end in _scan(text) if kind != "escape"]
    count, j = 0, text.find("$$")
    while j >= 0:
        if not (j and text[j - 1] == "\\") and not any(start <= j < end for start, end in covered):
            count += 1
        j = text.find("$$", j + 2)
    return count % 2 == 1


def _indent(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip(" "))


def _blocks(lines: list[str], tight: bool = False) -> list[str]:
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            body = inline_html("\n".join(para))
            out.append(body if tight else f"<p>{body}</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if para and _starts_block(line) and _open_display("\n".join(para)):
            para.append(line.strip())  # inside a $$ formula: "- x" is a minus, not a list
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence and (fence.group(2)[0] == "~" or "`" not in fence.group(3)):
            flush()
            mark, cut = fence.group(2), len(fence.group(1))
            closing = re.compile(rf"^[ \t]{{0,3}}{re.escape(mark[0])}{{{len(mark)},}}[ \t]*$")
            body = []
            i += 1
            while i < len(lines) and not closing.match(lines[i]):
                body.append(lines[i][cut:] if lines[i][:cut].strip() == "" else lines[i].lstrip())
                i += 1
            i += 1
            out.append(f"<pre><code>{escape(chr(10).join(body), quote=False)}</code></pre>")
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = min(len(heading.group(1)) + 2, 6)  # the page has h1 and h2; a doc's own headings start at h3
            out.append(f"<h{level}>{inline_html(heading.group(2) or '')}</h{level}>")
            i += 1
            continue
        if para and _SETEXT.match(line):
            level = 3 if line.strip()[0] == "=" else 4
            out.append(f"<h{level}>{inline_html(chr(10).join(para))}</h{level}>")
            para.clear()
            i += 1
            continue
        if _RULE.match(line):
            flush()
            out.append("<hr>")
            i += 1
            continue
        item = _ITEM.match(line)
        if item and (not para or item.group(3) is None or item.group(3) == "1") and (item.group(5) or "").strip() != "":
            flush()
            html, i = _list(lines, i)
            out.append(html)
            continue
        quote = _QUOTE.match(line)
        if quote:
            flush()
            inner = []
            while i < len(lines) and lines[i].strip():
                match = _QUOTE.match(lines[i])
                inner.append(match.group(1) if match else lines[i].strip())
                i += 1
            out.append(f"<blockquote>{''.join(_blocks(inner))}</blockquote>")
            continue
        para.append(line.strip())
        i += 1
    flush()
    return out


def _list(lines: list[str], i: int) -> tuple[str, int]:
    first = _ITEM.match(lines[i])
    assert first is not None
    ordered = first.group(3) is not None
    marker = first.group(2)[-1]
    items: list[list[str]] = []
    loose = False
    while i < len(lines):
        item = _ITEM.match(lines[i])
        if not item or not _same_list(item, ordered, marker):
            break
        content = _indent(item.group(1)) + len(item.group(2)) + len((item.group(4) or " ").expandtabs(4))
        body = [item.group(5) or ""]
        i += 1
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                k = i
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k < len(lines) and _indent(lines[k]) >= content:
                    body.extend("" for _ in range(k - i))
                    loose = True
                    i = k
                    continue
                nxt = _ITEM.match(lines[k]) if k < len(lines) else None
                if nxt and _indent(lines[k]) == _indent(first.group(1)) and _same_list(nxt, ordered, marker):
                    loose = True
                break
            if _indent(line) >= content:
                body.append(line.expandtabs(4)[content:])
                i += 1
                continue
            if _ITEM.match(line) or _HEADING.match(line) or _FENCE.match(line) or _QUOTE.match(line) or _RULE.match(line):
                break
            body.append(line.strip())  # a lazy continuation line
            i += 1
        items.append(body)
        if i < len(lines) and not lines[i].strip():
            k = i
            while k < len(lines) and not lines[k].strip():
                k += 1
            nxt = _ITEM.match(lines[k]) if k < len(lines) else None
            if nxt and _same_list(nxt, ordered, marker):
                i = k
                continue
            break
    tag = "ol" if ordered else "ul"
    start = int(first.group(3)) if ordered else 1
    attrs = f' start="{start}"' if ordered and start != 1 else ""
    rendered = "".join(f"<li>{''.join(_blocks(body, tight=not loose))}</li>" for body in items)
    return f"<{tag}{attrs}>{rendered}</{tag}>", i


def _same_list(item: re.Match[str], ordered: bool, marker: str) -> bool:
    """Another item of the same list: numbered or not as it is, with the same `-`, `*`, `+`, `.` or `)`."""
    return (item.group(3) is not None) == ordered and item.group(2)[-1] == marker
