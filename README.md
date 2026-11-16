# pareto-triage

Three hundred things look wrong in your codebase. You have a week. Which five do you fix?

This ranks them for you. It scans the code, weighs each problem by how much damage it can do against how much work it takes to fix, and tells you where the leverage is.

> I built it because every audit I'd been handed gave me a list. Long, alphabetical, sorted by nothing in particular.
>
> **I wanted the other thing:** the smallest set of fixes that buys the biggest return, and a clear way to park the rest until the next iteration.
>
> **Nothing gets written off.** The aim is still everything, eventually. Each round takes the slice with the most value for the least effort, so the business feels the improvement while the rest waits its turn.

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

- **shortcut** — the 80/20 holds. Fix these and stop.
- **concentrated-expensive** — real risk, expensive fix. Schedule it.
- **moderate** — spend an effort budget, don't chase the curve.
- **flat** — no shortcut exists, and it says so rather than inventing one.

Even a flat repo gets numbers: what 10% of the work buys, what half buys. "80% of the impact for 60% of the effort" is still a plan you can take to a standup.

## How it decides

22 rules catch what can be proven from a line: `eval`, shell injection, disabled TLS, committed keys, bare `except`, mutable defaults.

The judgement calls — missing timeouts, swallowed errors, no idempotency — go to the agent one function at a time, and it must quote the line it's judging. Invent a quote, lose the finding.

The maths never reaches the model. Two people running the same commands get the same ranking.

## Terminal instead

```sh
S=~/Development/pareto-triage/scripts/pareto-triage.py
R=/path/to/repo

python3 $S gate $R && python3 $S context $R && python3 $S detect $R
# your agent writes $R/out/failure-modes.jsonl
python3 $S validate $R/out/failure-modes.jsonl --repo $R
python3 $S rank $R && python3 $S report $R
```

`pareto-triage help` lists the rest, including `verify --fix`, which proves a patch turns a failing probe green.

## Honest limits

It cannot see through a DI container, an event bus, or a route built from a string. Reachability follows imports, understands `tsconfig` aliases and workspace names, and stops three hops out by default.

It has never audited a real repository: the tests run on three fixtures. Treat your first run as an experiment.

Secrets are masked in `report.html` and `report.json`. `out/defects.jsonl` keeps the raw line, so don't commit `out/`.

## Why I keep it small

No account, no upload, no telemetry. Your code stays on your disk, and the only thing that leaves is the HTML you choose to show someone. That was the whole design constraint, and it is why the tool is a script and a markdown file rather than a service.

---

MIT. Issues and pull requests welcome.
