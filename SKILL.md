---
name: pareto-triage
description: Scan a codebase, rank defects and failure modes by impact-per-effort, and test the Pareto bet — that a few fixes buy most of the robustness. Reports the measured shape of the curve (shortcut, moderate, flat, insufficient) instead of assuming 80/20. Use when asked to audit a codebase, prioritize fixes, find what to fix first, or assess how robust a project is.
---

# /pareto-triage

Find what to fix first, prove it, and never claim an 80/20 split the data does not support.

## When to run

- "What should we fix first?"
- "How robust is this codebase?"
- "Where is the risk in this repo?"
- Pre-acquisition, pre-handover, or pre-hire due diligence on a codebase.

## When to refuse

Refuse, and say why, when `pareto-triage gate` returns `ok: false`. The usual reasons: too little code to rank (under 10k non-blank lines), no detectable entrypoints (no reachability signal), or an unsupported language stack. Do not improvise a report on a repo that failed the gate.

## Phases

Run in order. Each phase writes one artifact under `<repo>/out/`. A phase must refuse when its input artifact is missing — never emit an empty file and call it success.

| Phase | Command | Produces |
|---|---|---|
| 0 Gate | `python3 scripts/pareto-triage.py gate <repo>` | `out/scope.json` |
| 0b Sites | `python3 scripts/pareto-triage.py context <repo>` | `out/context.jsonl`, `out/sample.json` |
| 1 Detect | `python3 scripts/pareto-triage.py detect <repo>` | `out/defects.jsonl` |
| 2 Enrich | you do this — read `references/prompts.md` | `out/failure-modes.jsonl`, `out/judgments.jsonl` |
| 3 Rank | `python3 scripts/pareto-triage.py rank <repo>` | `out/ranked.json` |
| 4 Report | `python3 scripts/pareto-triage.py report <repo>` | `out/report.html`, `out/report.json` |
| 5 Verify | `python3 scripts/pareto-triage.py verify <repo> [--scaffold]` | `out/verify.json` |
| 6 Calibrate | `python3 scripts/pareto-triage.py calibrate <repo>` | `out/calibration.jsonl`, `out/calibration.json` |

Requires Python 3.9+. No third-party packages.

If `python3` cannot run here, stop and say so. Do not estimate impact, effort, `c20`, or coverage yourself: a number you computed by reading code is not reproducible, and this skill's only claim is that its numbers are. Refusing is the correct result.

Phases 0, 0b, 1, 3, 4, and 5 are implemented by the scripts; phase 6 (calibration) is optional and is how you check phase 2 rather than trust it. Phase 2 is yours. Verification has three honest states: `reproduced` (a probe failed because of the defect), `fixed` (the same probe passed after `--fix`), and `unverified`. `fixed` means the test moved from red to green, not that the patch is correct.

## What the scan covers

`detect` runs 29 built-in rules that prove a construct exists at a line: eval/exec, `shell=True`, `Runtime.exec`/`ProcessBuilder` with concatenation, unsafe deserialization, SQL string interpolation (Java and Kotlin concatenation included), disabled TLS verification, committed secrets, bare except, empty and log-only catch, HTTP clients built without a timeout, mutable defaults, debug mode, MD5/SHA-1, XSS sinks. See `references/defect-rules.md`.

There are no Swift or Objective-C defect rules. `detect` prints rule coverage per language and names any supported language no rule could read; `rank` puts `no rules were applied to N files of Swift` (or Objective-C) into "Could not determine". Zero findings there means unassessed, not clean.

Everything requiring judgment — missing timeouts, swallowed errors, missing idempotency, unbounded work — is **not** covered by `detect`. If phase 2 has not run, the report says so in "Could not determine". Do not let a defects-only report read as a full audit.

Phase 2 is the only step where you exercise judgment. Everything else is deterministic. If a score ever depends on your opinion rather than a recorded number, the report stops being reproducible and is worthless.

## Phase 2 rules

1. Use `out/context.jsonl` from `pareto-triage context` — candidate sites already narrowed by reachability. Do not roam the whole repo, and do not add sites that are not in the file.
2. Propose only failure modes from `references/taxonomy.md`. No new categories.
3. Every finding needs a verbatim `evidence` quote, a `file` and `line`, and a `counter_evidence` sentence explaining why it might be fine.
4. A finding without all four is dropped, not softened.
5. Write JSONL matching the schema in `references/prompts.md`, then run `pareto-triage validate out/failure-modes.jsonl`. Fix rejections; do not bypass them.
6. Write `out/judgments.jsonl` as you judge: one `{"site_id": "s_001", "findings": 0}` per site you looked at, clean or not. `rank` counts a site as judged when it appears in `judgments.jsonl` or in `failure-modes.jsonl`. Without the file, a judged-and-clean site looks unjudged: coverage counts only sites with findings, `rank` warns that clean judgments are not recorded, and `--require-coverage` cannot pass.

## Coverage is part of the answer

`rank` records how many candidate sites phase 2 actually judged, and the report states it in "Could not determine". A site is judged when `out/judgments.jsonl` or `out/failure-modes.jsonl` names it, so a clean judgment counts the same as a finding. Judge every site, or say which you skipped. `rank --require-coverage 0.9` refuses a run below the threshold — use it when a partial pass would be read as a clean one.

## What you must never do

- Claim "80% of the value" or "the Pareto set" as if it were given. Report the measured concentration (`c20`), the verdict word, and the effort-for-impact ladder — those are measurements, and the ladder is what makes a non-shortcut report useful. State them as measured ratios; never as an assumption.
- Score without citing a line.
- Estimate hours, engineer-weeks, or money. Effort is an ordinal band (1–5) plus drivers.
- Edit the user's working tree. Verification happens in an isolated worktree.
- Mark a cluster verified without a probe that ran and failed. "Reproduced" is not "fixed".
- Publish a report with an empty "Could not determine" section.
- Rank people. This measures code, not performance.

## Always open the board

The work is not finished when the file is written. Finish by running `report <repo> --open`, which renders the HTML board and opens it in the browser. If no browser is available, print the path and say so — never end a run with the user hunting for a file.

A refusal is the exception: when the gate or the merge gate refuses, there is no board to open, and saying that plainly is the correct ending.

## Output contract

The curve always carries an effort-for-impact ladder: what share of the work buys 50%, 70% and 80% of the impact. Report the row that is true; never replace it with a verdict word. The one exception is fewer than three clusters: the verdict is `insufficient`, C20 is arithmetic rather than evidence, and the report omits the ladder. Say that instead of reporting a row.

Report sections, in this fixed order: **Shape** → **Curve** → **Quadrant** → **Top 5** → **Verification** → **Batch plan** → **All findings** → **Could not determine**. See `references/report-format.md`.

## References

- `references/rubric.md` — scoring scales, formulas, gates, version. Read before scoring anything.
- `references/defect-rules.md` — the 29 built-in rules, their severity, and the precision contract.
- `references/taxonomy.md` — the 13 failure modes, with counter-examples.
- `references/prompts.md` — versioned prompts and the JSONL schema.
- `references/entrypoints.md` — how reachability is derived, and where it lies.
- `references/report-format.md` — section order and required claims.
