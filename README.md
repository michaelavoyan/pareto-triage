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

One HTML file, no dashboard, no login. It opens with one of five answers:

| Verdict | What it means | What you do |
|---|---|---|
| `shortcut` | the 80/20 holds | fix these, stop |
| `concentrated-expensive` | real risk, expensive fix | schedule it properly |
| `moderate` | the curve is gentle | spend an effort budget |
| `flat` | no shortcut exists | stop looking for one |
| `insufficient` | fewer than three clusters; C20 is arithmetic | collect more findings, do not read a shape |

Even a flat repo gets numbers: what 10% of the work buys, what half buys. "80% of the impact for 60% of the effort" is still a plan you can take to a standup.

The report also says what carries the verdict: an attribution sentence splits the concentration between rule findings and judgment, so a rule-driven result is never read as a model conclusion.

## How it decides

26 rules catch what can be proven from a line: `eval`, shell injection, SQL built by concatenation, disabled TLS, committed keys, bare `except`, weak hashing, mutable defaults. That is the whole detector tier, and most of it is unmeasured. On the two real corpora it has been pointed at, the only incidence was a security rule: Signal-Android (828k lines) gave 1 finding, JobPilot (10k lines) gave 0 once the secret rule was limited to committed files.

A zero from a rule is not a clean bill. The report appendix lists every shipped rule with its hits in that scan; a rule the scan never exercised reads `0 hits (unexercised)` and its precision reads `unmeasured`.

The judgement calls — missing timeouts, swallowed errors, no idempotency — go to the agent one function at a time, and it must quote the line it's judging. Invent a quote, lose the finding.

Java and Kotlin are scanned for entrypoints, reachability, and defects. Four JVM rules cover command injection (`Runtime.exec` or `ProcessBuilder` with concatenation), SQL built by concatenation, `MessageDigest` with MD5 or SHA-1, and `new ObjectInputStream`. The secret rules run on `.java`, `.kt`, and `.kts` too.

Swift and Objective-C support is reachability and site extraction only. `#import` resolves header paths against the scanned tree, falling back to a basename only when exactly one scanned file carries it; Swift target membership comes from `project.pbxproj`, so two Swift files are neighbours only when they share a target and one names a type the other declares. `import Module` is not an edge: it names a module, not a file, and it produced 97% of the graph on Signal-iOS while carrying no call information. Entrypoints are `@main`/`@UIApplicationMain`/`UIApplicationMain(`, app delegates, and `UIViewController`/`UIView` subclasses through four hops of project bases, including ObjC `@interface` declarations; `context` extracts Swift and Objective-C functions as candidate sites.

**No Swift or Objective-C defect rules exist.** `detect` has nothing to run on `.swift`, `.m`, or `.mm`, so it reports rule coverage, prints `no rules were applied to N files of Swift` (or Objective-C), and `rank` writes the same sentence into `could_not_determine`. Zero findings there means unassessed, not clean.

The same-target rule is the limit that matters on a real tree. A separate framework target reached only through `import Framework` is unreachable: on Signal-iOS, 1,311 Swift files stayed at reach 1 — 44% of the code — because SignalServiceKit is its own target. A 200-site phase-2 calibration on the reachable part produced one cosmetic finding. iOS support buys reachability and candidate sites; it has not yet demonstrated real defects.

An entrypoint only counts when its language holds at least 5% of the supported lines. A repo whose seeds all come from a bundled helper language is refused, with the language named, rather than ranked on reachability that describes the tooling instead of the app.

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

## Honest limits

It cannot see through a DI container, an event bus, or a route built from a string. Reachability follows imports, understands `tsconfig` aliases and workspace names, and stops three hops out by default.

It has not produced a full audit of a real repository. The tests run on fixtures; the measurements quoted here come from running individual phases on Signal-iOS and Signal-Android, and the only phase-2 calibration on iOS was 200 sites yielding one cosmetic finding. Treat your first run as an experiment.

Secrets are masked in `report.html` and `report.json`. `out/defects.jsonl` keeps the raw line, so don't commit `out/`.

## Why I keep it small

No account, no upload, no telemetry. Your code stays on your disk, and the only thing that leaves is the HTML you choose to show someone. That was the whole design constraint, and it is why the tool is a script and a markdown file rather than a service.

---

**MIT.** Issues and pull requests welcome — especially from anyone who has run this on a codebase that isn't a fixture.
