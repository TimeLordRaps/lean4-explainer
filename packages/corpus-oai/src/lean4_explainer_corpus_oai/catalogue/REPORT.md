# Implication discovery: run report

## Environment

- toolchain: `Lean (version 4.34.1, x86_64-w64-windows-gnu, commit 5045d0056413266e57c625dcd7c365b10e377c52, Release)`
- mathlib: `d13f23b723b8a846827a245b89c10fc7d3f11612`
- corpus_repo: `openai/math`
- corpus_revision: `fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb`
- declarations extracted under rule set: `rules-1:e90530fde8cbabe9`

## Builds

| build | modules | seconds | stopped |
|---|---|---|---|
| build-challenges | built 416, replayed 69 | 7457.8 | — |
| build-probe | built 2 | 42.9 | — |


## Layer `statements`

- modules requested 415, extracted 415, in 6 environments (sizes [353, 52, 7, 1, 1, 1]); 79 pairs of modules declare the same name and were kept apart (0 more moved when an import failed), 0 batches split for other import failures
- declarations 18869: challenge-other 5927, interface 12406, statement 536
- statements (theorems whose type is a proposition) 4672; with sorry 577; unreadable 0
- extraction took 256.8 s

Discovery: policy `rules-1:c88d27fdc5e2730d`, budget {"heartbeats": 200000, "ms": 10000, "depth": 2, "discharge_heartbeats": 20000, "dischargers": ["omega", "norm_num", "positivity", "linarith"], "bound_closers": ["linarith", "nlinarith", "omega"]}, bounds {"per_target": 6, "per_link": 3, "per_compose": 4, "rare_df": 25, "min_shared": 1}

| candidate match | candidates | checked | outcomes |
|---|---|---|---|
| a second source supplies a hypothesis | 968 | 0 | budget 71, error 2, no-proof 798, rejected 2 |
| bound transfer | 6 | 0 | no-proof 6 |
| conclusion matches | 1459 | 6 | audit-failed 1, budget 87, checked 6, no-proof 1273 |
| conclusion supplies a hypothesis | 799 | 94 | audit-failed 5, budget 16, checked 94, error 85, no-proof 577, rejected 2 |
| equation | 807 | 0 | budget 24, no-proof 774 |

- 3823 attempts (1798 from the cache, 2025 run) in 8 environments, 10 Lean processes, 1051.2 s of Lean, 1053.2 s in all; attempt time 1769341 ms total, 20745 ms at most
- 2460 statements Lean generated (injectivity, equation lemmas; no source position) were not proposed
- 216 candidates not attempted: two of their modules declare the same name, so no environment holds them (47 module pairs; a second source supplies a hypothesis 95, conclusion matches 92, conclusion supplies a hypothesis 20, equation 9)

## Catalogue

- checked implications 100: connection 24, duplicate 3, one challenge 67, restatement 3, reverse direction 1, same statement 2
- by state: checked-derivation 100
- connections (checked, not grouped as routine) 24
- proof dependencies (from elaborated proof terms) 0
- unresolved attempts 3719: audit-failed 6, budget 198, error 87, no-proof 3428
- size: 2555935 bytes in 305 files

## Coverage

- `statements` families: statements 370, attempted 312, checked 38, connections 27
- `statements` areas: statements 22, attempted 22, checked 12, connections 9

## Curated contracts

- `seven-eighths-gives-an-explicit-real-zero-gap`: checked (checked 2026-10-10T22:56:22Z, environment 362897e7c89fc6ed2d1c)

