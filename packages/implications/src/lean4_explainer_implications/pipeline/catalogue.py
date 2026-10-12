"""Assemble what a run established into a catalogue: three kinds of record, kept apart.

dependencies  which corpus declarations a released proof uses, read from its elaborated proof term
implications  derivations Lean's kernel checked, with the sources as hypotheses (and, where the solution modules
              were built, applied to the released theorems and audited again)
unresolved    attempts that established nothing: no derivation within the rules, the budget ran out, the
              environment would not import. None of them says an implication is false.
rejected      derivations Lean checked that are not counted: one leaves a source unused, or its statement holds
              without any source (its own hypotheses or one tactic prove it)

Checked results that add nothing are grouped, not counted as connections: a statement checked against an identical
statement, a source passed through unchanged (the same proposition up to unfolding definitions), a lemma Lean
generated (it has no source position), two forms of one result its challenge lists together or a composition of
statements from one challenge file, a route the released proof already takes, a source
whose released proof already uses the target, the second direction of an equivalence, a source that is a structure's
field (extraction records Lean's projection info), and a derived statement another result already gives. Where a composition and a derivation of a named result give the same statement, the
named one is kept.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from .attempts import CHECKED
from .candidates import generated

FORMAT = 1
SHORT = 220


def _short(text: str, n: int = SHORT) -> str:
    one = re.sub(r"\s+", " ", text or "").strip()
    return one if len(one) <= n else one[: n - 1] + "…"


def rules_used(r: dict) -> list[str]:
    """The rules a checked derivation used, read from its recorded steps."""
    out = []
    steps = r.get("steps", [])
    kinds = {s.get("step") for s in steps}
    labels = " ".join(str(s.get("fact", "")) for s in steps)
    if r.get("rule") == "compose":
        out.append("short composition")
    elif len(r.get("sources", [])) > 1:
        out.append("joint derivation")
    if "apply" in kinds and any(s.get("substitutions") for s in steps if s.get("step") == "apply"):
        out.append("specialization")
    if "discharge" in kinds:
        out.append("premise discharge")
    if "left to right" in labels or "right to left" in labels:
        out.append("equivalence transport")
    if "rewrite" in kinds:
        out.append("equality rewriting")
    if "bound transfer" in kinds:
        out.append("bound transfer")
    if "witness transport" in kinds:
        out.append("witness transport")
    if "first part" in labels or "second part" in labels:
        out.append("conjunction part")
    return out or ["direct application"]


_ETA = re.compile(r"^fun source1\b(?P<binders>.*?)=>\s*source1(?P<args>(?:\s+[^\s()\[\]{}⦃⦄]+)*)$")


def _binders(text: str) -> tuple[list[str], set[str]]:
    """The explicit binder names of a printed `fun`, in order, and every binder name (implicit and instance too)."""
    tokens, cur, depth = [], "", 0
    for ch in text:
        if ch in "([{⦃":
            if depth == 0 and cur.strip():
                tokens.append(cur.strip())
                cur = ""
            depth += 1
            cur += ch
        elif ch in ")]}⦄":
            depth -= 1
            cur += ch
            if depth == 0:
                tokens.append(cur.strip())
                cur = ""
        elif ch.isspace() and depth == 0:
            if cur.strip():
                tokens.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        tokens.append(cur.strip())
    explicit, names = [], set()
    for tok in tokens:
        if tok[0] in "([{⦃":
            bound = tok[1:-1].split(":")[0].split()
            names.update(bound)
            if tok[0] == "(":
                explicit.extend(bound)
        else:
            explicit.append(tok)
            names.add(tok)
    return explicit, names


def restatement(r: dict) -> bool:
    """Whether a checked derivation passes its one source through unchanged: the proof is the source applied to the
    target's own variables in order (`fun source1 x y => source1 x y`), every substitution is one of those variables,
    and every other step is an assumption. Source and target then state one proposition up to unfolding definitions."""
    if r.get("rule") != "target" or len(r.get("source_keys") or []) != 1:
        return False
    m = _ETA.match(" ".join((r.get("proof") or "").split()))
    if not m:
        return False
    explicit, names = _binders(m["binders"])
    if m["args"].split() != explicit:
        return False
    for s in r.get("steps", []):
        if s.get("step") == "assumption":
            continue
        if s.get("step") == "apply" and s.get("source") == 1 and all(x.get("value") in names for x in s.get("substitutions", [])):
            continue
        return False
    return True


def directions(r: dict) -> list[str]:
    return sorted({f"{s.get('fact')}" for s in r.get("steps", []) if "left to right" in str(s.get("fact", "")) or "right to left" in str(s.get("fact", ""))})


def theorem_entry(d: dict) -> dict:
    rng = d.get("range") or {}
    return {
        "key": d["key"], "name": d["name"], "module": d["module"], "path": d["path"], "line": rng.get("line", 0),
        "role": d["role"], "kind": d.get("kind", ""), "family": d.get("family", ""), "area": d.get("area", ""),
        "challenge": d.get("challenge", ""), "statement": _short(d.get("type", ""), 400),
        "head": (d.get("norm") or {}).get("conclusion_head", ""), "sorry": bool(d.get("sorry")),
    }


def build(
    declarations: list[dict],
    results: list[dict],
    header: dict,
    contracts: list[dict] | None = None,
) -> dict:
    """The catalogue as one dict (`write` shards it). `declarations` are extraction records with identity; `results`
    are attempt results that carry `source_keys` and `target_key`."""
    seen_ids = set()
    for row in results:
        id_ = row.get("id")
        if not isinstance(id_, str) or not id_:
            raise ValueError("nonempty attempt id required")
        if id_ in seen_ids:
            raise ValueError(f"duplicate attempt id {id_}")
        seen_ids.add(id_)
    by_key = {d["key"]: d for d in declarations}
    proof_by_name: dict[str, list[dict]] = defaultdict(list)
    for d in declarations:
        if d["role"] in ("released", "helper"):
            proof_by_name[d["name"]].append(d)

    def resolve_proof_use(owner: dict, name: str) -> str:
        """Resolve a proof-term name without joining clashing extraction environments.

        A same-family declaration is authoritative. A cross-family declaration is usable only when the name is
        globally unique among extracted released/helper declarations; every ambiguity fails closed.
        """
        candidates = proof_by_name.get(name, [])
        if "env" in owner:
            # `env` is assigned by extraction. Two modules that clash are deliberately put in distinct environments;
            # a proof term can only refer to the declaration bearing this name in its own imported environment.
            same_environment = [d for d in candidates if d.get("env") == owner["env"]]
            return same_environment[0]["key"] if len(same_environment) == 1 else ""
        same_family = [d for d in candidates if owner.get("family") and d.get("family") == owner.get("family")]
        pool = same_family or candidates
        return pool[0]["key"] if len(pool) == 1 else ""

    proof_use_keys = {
        d["key"]: {key for name in d.get("proof_uses", []) if (key := resolve_proof_use(d, name))}
        for d in declarations if d["role"] in ("released", "helper")
    }

    def closure_uses(key: str, limit: int = 4000) -> tuple[set[str], set[str]]:
        names, seen_keys, todo = set(), set(), [key]
        while todo and len(seen_keys) < limit:
            current = todo.pop()
            declaration = by_key.get(current)
            if declaration is None:
                continue
            names.update(declaration.get("proof_uses", []))
            for used_key in proof_use_keys.get(current, ()):
                if used_key not in seen_keys:
                    seen_keys.add(used_key)
                    todo.append(used_key)
        return names, seen_keys

    releases_by_name: dict[str, list[dict]] = defaultdict(list)
    statement_families_by_name: dict[str, set[str]] = defaultdict(set)
    for d in declarations:
        if d["role"] == "released":
            releases_by_name[d["name"]].append(d)
        elif d["role"] == "statement":
            statement_families_by_name[d["name"]].add(d.get("family", ""))

    def released_copy(statement: dict | None) -> str:
        if statement is None:
            return ""
        if statement.get("role") == "released":
            return statement["key"]
        candidates = releases_by_name.get(statement["name"], [])
        family = statement.get("family")
        if family:
            candidates = [d for d in candidates if d.get("family") == family]
        same_type = [d for d in candidates if d.get("type_hash") == statement.get("type_hash")]
        pool = same_type or candidates
        return pool[0]["key"] if len(pool) == 1 else ""

    all_results = results
    # Each row of the instantiate stage applies one checked derivation to the released theorems: it changes that
    # derivation's state and is not a result of its own. More than one row would otherwise silently choose the last.
    applied = {}
    for row in results:
        derivation = row.get("derivation")
        if not derivation:
            continue
        if derivation in applied:
            raise ValueError(f"duplicate instantiation for derivation {derivation}")
        applied[derivation] = row
    results = [r for r in results if not r.get("derivation")]
    by_result_id = {r.get("id"): r for r in results if r.get("id")}
    for derivation, row in applied.items():
        original = by_result_id.get(derivation)
        if original is None:
            raise ValueError(f"orphan instantiation {derivation}")
        identity = lambda r: (r.get("rule", ""), tuple(r.get("source_keys", [])), r.get("target_key", ""))  # noqa: E731
        if identity(row) != identity(original):
            raise ValueError(f"instantiation does not match derivation {derivation}")
    derivations = CHECKED + ("instantiation-circular",)
    checked = [r for r in results if r.get("status") in derivations]
    rejected = [r for r in results if r.get("status") == "rejected"]
    unresolved = [r for r in results if r.get("status") not in derivations and r.get("status") != "rejected"]
    implications, by_statement = [], {}
    pairs = {(tuple(r["source_keys"]), r.get("target_key", "")) for r in checked}
    # a composite whose statement is a declaration's: which one (the hash only groups; it never makes a claim)
    by_type: dict[str, list[str]] = defaultdict(list)
    for d in declarations:
        if d.get("type_hash") and d.get("kind") == "theorem":
            by_type[d["type_hash"]].append(d["key"])
    for r in sorted(checked, key=lambda r: (r.get("rule") == "compose", len(r["source_keys"]), r["id"])):
        srcs, tgt = list(r["source_keys"]), r.get("target_key", "")
        inst = applied.get(r["id"])
        status = inst["status"] if inst and inst.get("status") in ("checked-instantiated", "instantiation-circular") else r["status"]
        sd = [by_key[k] for k in srcs if k in by_key]
        td = by_key.get(tgt)
        group, why = "connection", ""
        restates = [k for k in by_type.get(r.get("statement_hash", ""), []) if k not in srcs] if not tgt else []
        target_release = (inst or {}).get("verification_target_key", "") or released_copy(td)
        proof_names, proof_keys = closure_uses(target_release) if target_release else (set(), set())
        verification_sources = (inst or {}).get("verification_source_keys", [])
        exact_proof_route = bool(verification_sources) and all(k in proof_keys for k in verification_sources)

        def source_occurs_in_proof(source: dict) -> bool:
            if source["name"] not in proof_names:
                return False
            resolved = [by_key[k] for k in proof_keys if by_key.get(k, {}).get("name") == source["name"]]
            if resolved:
                return any(d.get("family") == source.get("family") for d in resolved)
            families = statement_families_by_name.get(source["name"], set()) - {""}
            target_family = by_key.get(target_release, {}).get("family", "")
            return len(families) <= 1 or source.get("family") == target_family

        if status == "instantiation-circular":
            group, why = "source uses the target", "a source's released proof already uses the target, so applied to the released theorems the route is circular"
        elif any(generated(x) for x in sd + ([td] if td else [])):
            group, why = "generated", "a source or the target is a lemma Lean generated (a constructor's injectivity, an equation lemma), not a stated result"
        elif td is None and len(sd) > 1 and all(s.get("challenge") and s.get("challenge") == sd[0].get("challenge") for s in sd):
            group, why = "one challenge", f"composes statements of one challenge file, {sd[0]['challenge']}"
        elif td is not None and len(sd) == 1 and sd[0].get("type_hash") == td.get("type_hash"):
            group, why = "same statement", "the source states exactly what the target states"
        elif td is not None and restatement(r):
            group, why = "restatement", "the proof passes the source through unchanged: the two state one proposition up to unfolding definitions"
        elif td is not None and sd and all(s.get("challenge") and s.get("challenge") == td.get("challenge") for s in sd):
            group, why = "one challenge", f"{td['challenge']} lists source and target as forms of one result"
        elif td is not None and sd and (exact_proof_route or (not verification_sources and all(source_occurs_in_proof(s) for s in sd))):
            group, why = "in the released proof", "the target's released proof already goes through the source"
        elif td is not None and len(sd) == 1 and ((tgt,), srcs[0]) in pairs and srcs[0] > tgt:
            # both directions were checked: list the pair once, as an equivalence
            group, why = "reverse direction", "the other direction is listed too: the two statements are equivalent"
        elif field := next((s["projection"] for s in sd if s.get("projection")), None):
            group, why = "structure field", (f"a source is the field `{field['field']}` of `{field['structure']}`: a fact every "
                                             f"`{field['structure']}` carries by its definition, so the derivation applies to what that structure requires")
        h = r.get("statement_hash", "")
        if group == "connection" and h:
            if h in by_statement:
                group, why = "duplicate", f"derives the same statement as {by_statement[h]}"
            else:
                by_statement[h] = r["id"]
        family = (td or (sd[0] if sd else {})).get("family", "")
        # what a composition's first source supplies to the second, as Lean recorded it (older results did not)
        supply = next((x for x in r.get("steps", []) if x.get("step") == "supply"), None)
        link = None if supply is None or "hypothesis_head" not in supply else {
            "hypothesis": supply.get("hypothesis", ""), "head": supply["hypothesis_head"], "positivity": bool(supply.get("positivity"))}
        implications.append({
            "id": r["id"], "state": "checked-instantiated" if status == "checked-instantiated" else "checked-derivation",
            "restates": restates,
            "rules": rules_used(r), "directions": directions(r), "group": group, "group_reason": why,
            "sources": srcs, "target": tgt, "family": family,
            "families": sorted({x.get("family", "") for x in sd + ([td] if td else []) if x.get("family")}),
            "statement": r.get("statement", ""), "derived": r.get("derived", ""), "used": r.get("used", []),
            "steps": r.get("steps", []), "substitutions": r.get("substitutions", []), "proof": r.get("proof", ""),
            "axioms": r.get("axioms", []), "instantiated_axioms": r.get("instantiated_axioms") or (inst or {}).get("instantiated_axioms", []),
            "instantiation": None if inst is None else {
                "id": inst["id"], "status": inst.get("status", ""), "reason": _short(inst.get("reason", ""), 300),
                "verification_sources": inst.get("verification_source_keys", []),
                "verification_target": inst.get("verification_target_key", ""),
                "environment": {"id": inst.get("env_id", ""), "modules": inst.get("env_modules", 0)},
                "cost": {"ms": inst.get("ms", 0), "heartbeats_thousands": inst.get("heartbeats", 0)}},
            "link": link, "match": r.get("match", ""), "shared": r.get("shared", []),
            "environment": {"id": r.get("env_id", ""), "modules": r.get("env_modules", 0), "layer": r.get("layer", "")},
            "cost": {"ms": r.get("ms", 0), "heartbeats_thousands": r.get("heartbeats", 0)},
        })
    # only theorems a checked entry names: the rest would be most of the index and show nothing (other rows keep keys)
    involved = {k for i in implications for k in i["sources"] + ([i["target"]] if i["target"] else []) + i["restates"]
                + ((i.get("instantiation") or {}).get("verification_sources") or [])
                + ([(i.get("instantiation") or {}).get("verification_target")] if (i.get("instantiation") or {}).get("verification_target") else [])}
    theorems = {d["key"]: theorem_entry(d) for d in declarations if d["key"] in involved}
    # proof dependencies among corpus declarations, read from released proof terms
    dependencies = []
    for d in declarations:
        if d["role"] not in ("released", "helper") or d.get("kind") != "theorem":
            continue
        uses = sorted(proof_use_keys.get(d["key"], ()))
        if uses:
            dependencies.append({"from": d["key"], "uses": uses, "family": d.get("family", "")})
    unresolved_rows = [{
        "id": r["id"], "status": r.get("status", ""), "reason": _short(r.get("reason", ""), 300), "rule": r.get("rule", ""),
        "sources": r.get("source_keys", []), "target": r.get("target_key", ""), "match": r.get("match", ""),
        "family": (by_key.get(r.get("target_key", "")) or by_key.get((r.get("source_keys") or [""])[0]) or {}).get("family", ""),
        "cost": {"ms": r.get("ms", 0), "heartbeats_thousands": r.get("heartbeats", 0)},
    } for r in unresolved]
    rejected_rows = [{
        "id": r["id"], "reason": _short(r.get("reason", ""), 300), "rule": r.get("rule", ""),
        "sources": r.get("source_keys", []), "target": r.get("target_key", ""), "statement": _short(r.get("statement", "")),
        "family": (by_key.get(r.get("target_key", "")) or by_key.get((r.get("source_keys") or [""])[0]) or {}).get("family", ""),
    } for r in rejected]
    counts = {
        "theorems_indexed": len(theorems),
        "checked": len(implications),
        "checked_by_group": dict(Counter(i["group"] for i in implications)),
        "checked_by_state": dict(Counter(i["state"] for i in implications)),
        "instantiation": dict(Counter(r.get("status", "") for r in applied.values())),
        "connections": sum(i["group"] == "connection" for i in implications),
        "connections_by_link": dict(Counter(link_kind(i) for i in implications if i["group"] == "connection")),
        "dependencies": sum(len(d["uses"]) for d in dependencies),
        "unresolved": len(unresolved_rows),
        "unresolved_by_status": dict(Counter(r["status"] for r in unresolved_rows)),
        "rejected": len(rejected_rows),
        "rejected_by_reason": dict(Counter(_reason_kind(r["reason"]) for r in rejected_rows)),
    }
    # the rule set the results were checked under, as they record it, not the one current when this was assembled
    policies = sorted({r["policy"] for r in all_results if r.get("policy")})
    if policies:
        header = {**header, "policy": ", ".join(policies)}
    return {"format": FORMAT, **header, "counts": counts, "theorems": theorems, "implications": implications,
            "dependencies": dependencies, "unresolved": unresolved_rows, "rejected": rejected_rows, "contracts": contracts or []}


def _reason_kind(reason: str) -> str:
    if reason.startswith("does not use"):
        return "a source is unused"
    if reason.startswith("the statement holds without the sources"):
        return "holds without the sources"
    return reason.split(":")[0][:60]


def _shard_name(family: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", family or "other").strip("-").lower() or "other"
    return f"{slug[:48]}-{hashlib.sha256(family.encode()).hexdigest()[:6]}"


def link_kind(entry: dict) -> str:
    """What links a composition's sources: a quantity's positivity, else the head of the supplied hypothesis."""
    link = entry.get("link")
    if not link:
        return "derives a named result" if entry.get("target") else "not recorded"
    return "positivity" if link["positivity"] else link["head"]


def write(cat: dict, out: Path) -> dict[str, int]:
    """Write the catalogue as a small index plus shards per family, so a page loads only what it shows."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "shards").mkdir(exist_ok=True)
    shards: dict[str, dict] = defaultdict(lambda: {"implications": [], "dependencies": [], "unresolved": [], "rejected": []})
    for kind in ("implications", "dependencies", "unresolved", "rejected"):
        for row in cat[kind]:
            shards[_shard_name(row.get("family", ""))][kind].append(row)
    index_rows = [{
        "id": i["id"], "state": i["state"], "group": i["group"], "rules": i["rules"], "sources": i["sources"],
        "target": i["target"], "restates": i["restates"], "families": i["families"], "statement": _short(i["statement"]),
        "shard": _shard_name(i.get("family", "")), "layer": i["environment"]["layer"], "link": link_kind(i) if i.get("link") else "",
    } for i in cat["implications"]]
    index = {k: v for k, v in cat.items() if k not in ("implications", "dependencies", "unresolved", "rejected")}
    index["implications"] = index_rows
    index["shards"] = {name: {kind: len(rows) for kind, rows in s.items()} for name, s in sorted(shards.items())}
    index["unresolved_summary"] = summarize_unresolved(cat["unresolved"])
    sizes = {}
    for name, s in shards.items():
        text = json.dumps(s, ensure_ascii=False, separators=(",", ":"))
        (out / "shards" / f"{name}.json").write_text(text, encoding="utf-8")
        sizes[f"shards/{name}.json"] = len(text.encode())
    for old in (out / "shards").glob("*.json"):  # a family with no entries now must not leave its shard to be published
        if f"shards/{old.name}" not in sizes:
            old.unlink()
    text = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    (out / "index.json").write_text(text, encoding="utf-8")
    sizes["index.json"] = len(text.encode())
    return sizes


def summarize_unresolved(rows: Iterable[dict]) -> list[dict]:
    """Unresolved attempts by status and the first words of their reason."""
    groups: Counter = Counter()
    for r in rows:
        # Lean's internal ids (`_fvar.1889142`, `_uniq.77`) differ per attempt and say nothing about the cause
        reason = re.sub(r"\b_(fvar|uniq|mvar)\.\d+", r"_\1.…", r["reason"].split(":")[0][:80])
        groups[(r["status"], reason)] += 1
    return [{"status": s, "reason": why, "count": n} for (s, why), n in groups.most_common()]
