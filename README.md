# pareto-triage

Three hundred things look wrong in your codebase. You have a week. Which five do you fix?

This answers that. It scans the code and ranks what it finds by impact per unit of effort. The bet is Pareto: a few fixes buy most of the robustness. The tool tests that bet on your codebase rather than assuming it.

Either way you get a number. If 80% of the impact costs 12% of the work, that's the headline. If it costs 60%, the report says 60% — and still shows the best set you can buy: what 10% of the effort gets you, what 30% gets you, where the curve bends. There is no page that just says "no shortcut, good luck".

## What it does

It walks the code from its entrypoints — routes, CLI commands, cron jobs — and collects the functions a request can actually reach. Then it runs 22 rules over them: `eval`, shell injection, disabled TLS checks, committed keys, bare `except`, mutable defaults. Those are facts, not opinions.

Everything that needs judgment — missing timeouts, swallowed errors, no idempotency — is where the agent earns its keep. It judges one function at a time and has to quote the line it's talking about. Fabricate the quote and the tool rejects the finding.

Then the arithmetic happens in code, not in a model's head. Impact, effort, clusters, and how much of the impact the top fifth actually carries. The report says one of four things: `shortcut` (the 80/20 holds, fix these and ignore the rest), `concentrated-expensive` (the risk is real, the fix is not cheap), `moderate`, or `flat` — the bet failed, there is no shortcut, and pretending otherwise would be the one lie this tool refuses to tell.

You get one HTML file. No JavaScript, no dashboard, no login.

## Install

Needs Python 3.9. Nothing else. No packages, no network.

```sh
git clone https://github.com/michaelavoyan/pareto-triage ~/Development/pareto-triage
ln -s ~/Development/pareto-triage ~/.config/opencode/skills/pareto-triage
```

Claude Code reads the same file from `~/.claude/skills/`. Any other agent: point it at `SKILL.md`.

## Use it

Say this to your agent:

```
Use pareto-triage on this repo and tell me what to fix first.
```

It runs the phases and hands you `out/report.html`. If the repo is too small or has no entrypoints, it refuses instead of inventing a ranking. That refusal is the feature.

Prefer the command line? The whole pipeline is seven commands and a report:

```sh
S=~/Development/pareto-triage/scripts/pareto-triage.py
python3 $S gate    /path/to/repo
python3 $S context /path/to/repo
python3 $S detect  /path/to/repo
# the agent writes out/failure-modes.jsonl here
python3 $S validate /path/to/repo/out/failure-modes.jsonl --repo /path/to/repo
python3 $S rank    /path/to/repo
python3 $S report  /path/to/repo
python3 $S verify  /path/to/repo --scaffold   # optional: a probe template per top cluster
```

`pareto-triage help` lists the rest, including `--fix` for proving a patch turns red into green.

## What it won't do

It won't see through a dependency-injection container, an event bus, or a string-built route. Reachability follows imports, takes `tsconfig` aliases and workspace names into account, and stops at three hops by default.

It won't hand you a percentage you can quote. If the shape is flat, it says flat.

And it hasn't audited a real repository yet — every test runs on three fixtures. Treat the first run on your code as an experiment, not a verdict.

## What it will not publish

Secrets. Detected keys are masked in `report.html` and `report.json` before they're written. `out/defects.jsonl` still holds the raw line, so don't commit `out/`.

---

MIT. Ideas and bug reports welcome.
