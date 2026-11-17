# pareto-triage

<p>
  <img alt="tests" src="https://github.com/michaelavoyan/pareto-triage/actions/workflows/test.yml/badge.svg">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-blue">
  <img alt="dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen">
</p>

*Find the five fixes that matter, and forget the other two hundred and ninety-five.*

Three hundred things look wrong in your codebase. You have a week. Which five do you fix?

This ranks them for you. It scans the code, weighs each problem by how much damage it can do against how much work it takes to fix, and tells you where the leverage is.

> I built it because every audit I'd been handed gave me a long list. Just a list — never sorted by what actually mattered first.
>
> **I wanted the other thing:** the smallest set of fixes that buys the biggest return, and a clear way to park the rest until the next iteration.
>
> **Nothing gets written off.** The aim is still everything, eventually. Each round takes the slice with the most value for the least effort, so the business feels the improvement while the rest waits its turn.
>
> The same shape shows up almost everywhere, by the way. A few customers, a few habits, a few people — most of the effect comes from a small part of the input. Code is just where I can measure it.

## Try it

Python 3.9, no packages, no network.

```sh
git clone https://github.com/michaelavoyan/pareto-triage ~/Development/pareto-triage
ln -s ~/Development/pareto-triage ~/.config/opencode/skills/pareto-triage
```

Claude Code takes the same file from `~/.claude/skills/`. Anything else: point it at `SKILL.md`.

Then ask:

```
Use pareto-triage on this repo and tell me what to fix first.
```

You get `out/report.html`. If the repo is too small or has no entrypoints, it refuses instead of inventing a ranking. That refusal is the point.

## What comes back

One HTML file, no dashboard, no login. It opens with one of four answers:

| Verdict | What it means | What you do |
|---|---|---|
| `shortcut` | the 80/20 holds | fix these, stop |
| `concentrated-expensive` | real risk, expensive fix | schedule it properly |
| `moderate` | the curve is gentle | spend an effort budget |
| `flat` | no shortcut exists | stop looking for one |

Even a flat repo gets numbers: what 10% of the work buys, what half buys. "80% of the impact for 60% of the effort" is still a plan you can take to a standup.

## How it decides

27 rules catch what can be proven from a line: `eval`, shell injection, SQL built by concatenation, disabled TLS, committed keys, bare `except`, empty `catch`, weak hashing, mutable defaults.

The judgement calls — missing timeouts, swallowed errors, no idempotency — go to the agent one function at a time, and it must quote the line it's judging. Invent a quote, lose the finding.

Java and Kotlin are scanned for entrypoints, reachability, and defects. Five JVM rules cover command injection (`Runtime.exec` or `ProcessBuilder` with concatenation), SQL built by concatenation, empty `catch`, `MessageDigest` with MD5 or SHA-1, and `new ObjectInputStream`. The secret rules run on `.java`, `.kt`, and `.kts` too.

The maths never reaches the model. Two people running the same commands get the same ranking.

`context` fills its cap with a seeded random sample by default; `--sample-order ranked` restores the reach → inbound → size order that measured no better than random on Signal-Android, and `sampling` re-runs that comparison against a seeded random sample of the same size.

## Terminal instead

```sh
S=~/Development/pareto-triage/scripts/pareto-triage.py
R=/path/to/repo

python3 $S gate $R && python3 $S context $R && python3 $S detect $R
# your agent writes $R/out/failure-modes.jsonl and $R/out/judgments.jsonl
python3 $S validate $R/out/failure-modes.jsonl --repo $R
python3 $S rank $R && python3 $S report $R
```

`pareto-triage help` lists the rest, including `verify --fix`, which proves a patch turns a failing probe green.

## Artifacts

Everything lands in `<repo>/out/`. Nothing is uploaded.

| Artifact | Written by | Contains | Exposure |
|---|---|---|---|
| `scope.json` | `gate` | file and language counts, entrypoint list, warnings | Safe to share; no source |
| `context.jsonl`, `candidates.jsonl` | `context` | function bodies and surrounding lines | Local only; contains source |
| `sample.json` | `context` | sampling mode, seed, population, cap | Safe to share |
| `defects.jsonl` | `detect` | rule findings with verbatim evidence, secrets unmasked | Local only; never commit |
| `failure-modes.jsonl` | phase 2 | judged findings with evidence quotes | Local only; contains source |
| `judgments.jsonl` | phase 2 | one `site_id` and finding count per judged site | Safe to share; no source, only ids and counts |
| `ranked.json` | `rank` | scores, clusters, coverage, finding evidence | Local only; evidence is not redacted until `report` |
| `report.html`, `report.json` | `report` | the board and its JSON, secrets redacted | Safe to share |
| `verify.json` | `verify` | probe results and evidence | Local only; contains source |
| `calibration.jsonl`, `calibration.json` | `calibrate` | sampled findings and verdicts | Local only; contains evidence |

`judgments.jsonl` is the coverage ledger. Phase 2 writes one record per site it judged, including sites with zero findings, so `rank` can tell “judged clean” from “not judged”. Without it, coverage counts only sites with a finding; `rank` warns and `--require-coverage` cannot pass on a clean repo.

## Honest limits

It cannot see through a DI container, an event bus, or a route built from a string. Reachability follows imports, understands `tsconfig` aliases and workspace names, and stops three hops out by default.

It has never audited a real repository: the tests run on three fixtures. Treat your first run as an experiment.

Secrets are masked in `report.html` and `report.json`. `out/defects.jsonl` keeps the raw line, so don't commit `out/`.

## Why I keep it small

No account, no upload, no telemetry. Your code stays on your disk, and the only thing that leaves is the HTML you choose to show someone. That was the whole design constraint, and it is why the tool is a script and a markdown file rather than a service.

---

**MIT.** Issues and pull requests welcome — especially from anyone who has run this on a codebase that isn't a fixture.
