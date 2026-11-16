# pareto-triage

Three hundred things look wrong in your codebase. You have a week. Which five do you fix?

That's the question this answers. It scans the code, ranks what it finds by impact per unit of effort, and tells you which fixes actually buy the most robustness.

## How it works

It starts at your entrypoints — routes, CLI commands, cron jobs — and collects the functions a request can really reach. Then 22 rules look for facts: `eval`, shell injection, disabled TLS checks, committed keys, bare `except`, mutable defaults.

The judgement calls — missing timeouts, swallowed errors, no idempotency — go to the agent, one function at a time. It has to quote the line it's complaining about. Invent the quote and the finding is thrown out.

The arithmetic never goes to the model. Impact, effort, clusters, concentration: computed, so two people get the same ranking.

## What you get

One HTML file. No JavaScript, no dashboard, no login.

It opens with the shape of your problem:

- **shortcut** — the 80/20 holds. Fix these, ignore the rest.
- **concentrated-expensive** — the risk is real, the fix is not cheap.
- **moderate** — use an effort budget.
- **flat** — there is no shortcut, and the report says so instead of inventing one.

Even then you get numbers. "80% of the impact for 60% of the work" is still a plan. The curve shows what 10%, 30% and half your effort would buy, so you can pick a budget and see the return.

## Install

Python 3.9 and nothing else. No packages, no network.

```sh
git clone https://github.com/michaelavoyan/pareto-triage ~/Development/pareto-triage
ln -s ~/Development/pareto-triage ~/.config/opencode/skills/pareto-triage
```

Claude Code reads the same file from `~/.claude/skills/`. Anything else: point it at `SKILL.md`.

## Use

Ask your agent:

```
Use pareto-triage on this repo and tell me what to fix first.
```

You get `out/report.html`. If the repo is too small or has no entrypoints, it refuses rather than inventing a ranking. That refusal is the feature.

Prefer the terminal? Seven commands:

```sh
S=~/Development/pareto-triage/scripts/pareto-triage.py
R=/path/to/repo

python3 $S gate    $R     # will it even rank this repo?
python3 $S context $R     # functions worth judging
python3 $S detect  $R     # the facts
# your agent writes $R/out/failure-modes.jsonl here
python3 $S validate $R/out/failure-modes.jsonl --repo $R
python3 $S rank    $R     # scores and shape
python3 $S report  $R     # out/report.html
```

`pareto-triage help` has the rest, including `verify --fix` for proving a patch turns a failing probe green.

## What it won't do

It won't see through a dependency-injection container, an event bus, or a route built from a string. Reachability follows imports, understands `tsconfig` aliases and workspace names, and stops three hops out by default.

It won't hand you a percentage you can quote. If the shape is flat, the report says flat.

And it has never audited a real repository yet — the tests run on three fixtures. Treat your first run as an experiment, not a verdict.

## Secrets

Detected keys are masked before `report.html` and `report.json` are written. `out/defects.jsonl` keeps the raw line, so don't commit `out/`.

---

MIT. Issues and pull requests welcome.
