# Rubric

Scoring is deterministic. Given the same findings and this document, two people must produce identical rankings. If they do not, the rubric is wrong — fix the rubric, not the scores.

Change log:
- 1.5.0 — attribution: the C20 share is split by finding class (rule defect vs judgment), overall and inside the top fifth, with a per-class verdict.
- 1.4.0 — a shape verdict needs at least three clusters; below that C20 is arithmetic, the verdict is `insufficient`, and no `shortcut` is claimed.
- 1.0.0 — initial. Reach gate, impact = blast × silence / 3, priority = impact / effort, noisy-OR clustering.
- 1.3.0 — effort budgets S/M/L (5/15/30 units) are defined for the curve markers; no score changes.
- 1.2.0 — the reach discount (`reach == 1` → impact × 0.25) and the reach-0 drop are enforced in scoring; the 0–5 scale is now produced, not just documented.
- 1.1.0 — "crosses a module boundary" is defined, and applies to the reduced defect formula as written; failure-mode effort is measured from call sites instead of estimated by the model.

## Axes

### reach (0–5) — how reachable from the outside world

The 0–5 scale, and which entrypoint seeds each level, is defined once in `references/entrypoints.md`. Scoring uses it two ways:

- `reach == 0` → the finding is dropped before clustering.
- `reach == 1` → impact is multiplied by 0.25.

Levels 2–5 carry no multiplier. Reach is a heuristic; when it came from file-level imports rather than a symbol-level call path, the report says so under "Could not determine".

### blast (0–5) — how bad it is when it fires

| | Consequence |
|---|---|
| 5 | Data loss or corruption, security breach, money movement error |
| 4 | Wrong output that looks right; a user acts on bad data |
| 3 | Stuck work: queue stalls, retries exhausted, job never completes |
| 2 | Crash, 500, or failed request — noisy but recoverable |
| 1 | Degraded UI, slow path, cosmetic |

### silence (1–3) — how quietly it fails

| | Behaviour |
|---|---|
| 3 | Silently wrong: swallows the error, returns a default, logs nothing |
| 2 | Logged only; no alert, no retry, nobody paged |
| 1 | Fails loudly: throws, crashes, surfaces to the user |

Silence is the axis no existing tool ranks, and it is why this rubric exists. A silent data-corrupting bug outranks a loud crash in a utility.

### effort (1–5, ordinal only)

Not hours. Never hours.

```
effort = clamp(1 + files/3 + callsites/5 + (crosses_boundary ? 1 : 0) + (no_test ? 1 : 0), 1, 5)
```

Record the drivers in `effort_drivers`. Effort is only required to be ordinally correct: the ranking needs "this is cheaper than that", never "this takes 3.5 hours".

## Derived values

### pareto point

```
pareto_point(target) = the shortest priority-ordered prefix of clusters whose
                       impact first reaches target × total impact
                     = its effort ÷ total effort

Note "priority-ordered prefix", not "the cheapest possible subset": a cheaper
combination can exist out of order, and this reports the set a reader can work
through top-down, not an optimisation problem.
```

Reported as a pair, never as a verdict alone: target (50%, 70%, 80%) against the share of effort it costs. `shortcut` is true only when 80% of the impact costs at most half the effort. A repo where that set costs 60% is not a failure — the 50% row is still the answer to "what can I buy this week".

```
impact   = (blast × silence) / 3          // [0, 5]
priority = impact / effort
```

## Effort for a built-in defect rule

A rule match is a mechanical, local change with no design decision:

```
effort = 1 + (no test runner ? 1 : 0) + (crosses a module boundary ? 1 : 0)
```

Record the drivers. This is the only variant of the effort formula; everything else uses the five-term version above.

### What "crosses a module boundary" means

A file's package is its first two path segments: `src/api/routes.ts` lives in `src/api`, `src/db/store.ts` in `src/db`. A file at the repository root has no package. The boundary is crossed when the fixed file and any file importing it sit in different packages.

This is a path heuristic, not a build-system fact. A monorepo whose packages are two levels deep is handled; one nested deeper is not, and says so here rather than guessing.

### Confidence caps

`high` means a tool detector proved the construct is there. When the gate finds
no test runner, no fix can be verified, so every finding is capped at `med` and
carries `confidence_capped: true` plus the reason. The cap is applied in
`detect` and again in `rank`, so a hand-written findings file cannot bypass it,
and `validate --max-confidence` rejects a record that claims more.

### Where the numbers come from

Drivers are measured, never written by hand: `files` counts the fixed file plus the distinct source files that mention the enclosing function, `callsites` counts those mentions (an import counts as a mention), and `no test runner` comes from the gate. A handler with no symbol to count — an inline route callback — is reported as one file, one site, and the driver says so.

The model does not supply `effort` for a failure mode. Phase 2 records evidence and judgement; arithmetic happens in `rank`, from the code.

## Effort budgets

The curve marks three budgets in effort units: S = 5, M = 15, L = 30. They describe a work session, not a calendar; the tool never converts them to hours. Override with `--budget S,M,L` when a repo's effort distribution makes the defaults useless.

## Clustering

Group by `(rule | taxonomy)`. One pattern in nine places is one fix.

```
cluster_impact = 5 × (1 - Π(1 - impact_i / 5))          // noisy-OR, back on 0-5
cluster_effort = effort_rep × (1 + 0.4 × (n - 1))
                 capped at Σ effort_i
cluster_priority = cluster_impact / cluster_effort
```

The noisy-OR treats each site as an independent chance the system misbehaves. That assumption is false when sites share a blast radius — say so in the report when it applies.

## Shape

```
sort clusters by impact desc
C20 = impact share of the top 20% of clusters (effort ignored when sorting)
```

`C20` answers one question only: is impact concentrated? It says nothing about whether the concentrated items are cheap — that is what the effort column of the same top set answers.

| C20 | Top clusters | Verdict |
|---|---|---|
| ≥ 0.60 | mostly effort ≤ 2 | `shortcut` |
| ≥ 0.60 | mostly effort ≥ 4 | `concentrated-expensive` |
| 0.30–0.60 | any | `moderate` |
| < 0.30 | any | `flat` |

A verdict needs **at least three clusters**. Below that the top fifth of the
clusters is a single cluster, so C20 is not a share of anything: with one
cluster it is 1.0 by arithmetic, and with two it is whichever one happens to be
larger. `shape.c20` is still reported as a number, `shape.n_clusters` says how
many there were, and `shape.verdict` is `insufficient` with
`shape.min_clusters` = 3. The report says the verdict is not meaningful at that
cluster count. The Pareto ladder is not printed, and no `shortcut` claim is
made: when the shape is `insufficient`, every `pareto` and `pareto_ladder` row
reports `shortcut: false` so the two numbers cannot disagree.

Only `shortcut` justifies "fix these few and stop." `flat` means returns track effort — say so plainly.

## Attribution

A cluster's class is the class of its findings: `defect` for a built-in rule, `failure-mode` for phase-2 judgment. The C20 set is the top `ceil(0.2 × n)` clusters by impact, exactly as Shape defines it.

```
class_impact    = Σ impact of that class's clusters
class_share     = class_impact / Σ impact of all clusters
class_top       = Σ impact of that class's clusters inside the C20 set
class_top_share = class_top / Σ impact of the C20 set
class_verdict   = shape(that class's clusters alone)
```

`ranked.json` records this as `attribution.<class>.{clusters, findings, impact, share, top.{clusters, impact, share}, verdict}` for `defect` and `failure_mode`. `share` is of total impact; `top.share` is the share of the concentration, and is the number the report prints. A class with no clusters reports zero and `empty`, not a percentage of nothing. The per-class verdict is what makes "judgment alone would be insufficient" checkable rather than asserted.

## Quadrant

Medians are computed with the standard median (mean of the middle pair for an
even count), not the upper-middle item.

```
quick_wins = impact ≥ median ∧ effort ≤ median   → do now
batch_2    = impact ≥ median ∧ effort  > median   → schedule
free       = impact <  median ∧ effort ≤ median   → anytime
skip       = impact <  median ∧ effort  > median   → ignore
```

## Reporting counts

When n < 15, report counts, not percentages: "closes 4 of the 5 silent-failure paths". A percentage on seven items is decoration.
