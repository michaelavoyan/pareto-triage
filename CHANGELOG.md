# Changelog

## 0.3.0

- `context` fills its site cap with a seeded random sample by default
  (`--sample-order random`, `--seed N`). The old reach → inbound → body size
  order is kept as `--sample-order ranked`, unchanged.
- The change follows a measurement, not a preference: on Signal-Android at
  5,000 sites per arm the ranked order and a seeded random sample were
  indistinguishable on rule findings (file-density ratio 0.98, 95% CI
  −0.0057..+0.0049). `references/entrypoints.md` now records that result in
  place of the claim that the order predicts value.
- `context` prints the sampling method and writes `out/sample.json`
  (`mode`, `seed`, `population`, `kept`, `per_file`). `context.jsonl` keeps its
  record-only shape. `report` repeats the method under "Could not determine".
- `sampling` warns when `candidates.jsonl` starts with a shuffled sample, so a
  random population is not mistaken for the ranked comparison.

## 0.2.1

- Test code is excluded from candidate sites, import edges and entrypoints:
  `androidTest/`, `test/`, `*Test`, `*Tests`, `*IT`, `*Spec`, Python `test_*`,
  and `.test`/`.spec` files. On Signal-Android the first candidate sites were
  test helpers; they are now production classes.
- `report --open` renders and opens the HTML board; the skill requires ending a
  run with the board open.

## 0.2.0

- Java and Kotlin are supported languages: the gate counts their lines, imports
  resolve across Maven/Gradle layouts, and methods, `fun`s and class bodies
  become candidate sites.
- Entrypoints: `public static void main`, `fun main`, Spring and JAX-RS
  annotations.
- Same-package Java edges require the peer type name to appear in the importing
  file; visibility alone does not lift a whole package.
- **No JVM defect rules yet.** On a Java or Kotlin repo `detect` returns zero
  findings, so a report covers reachability and phase-2 judgment only.
- README states the supported languages and that limit.

## 0.1.1

- README rewritten for a first-time reader: usage before explanation, the four
  verdicts as a table, badges, and the first-person note on why the tool exists.
- The changelog no longer opens with an empty `Unreleased` heading.

## 0.1.0

First release.

- Scan: `gate` refuses a repo where a ranking would be invented; `context` emits one record per function reachable from an entrypoint; `detect` runs 22 rules, secrets included; `validate` enforces verbatim evidence, site correspondence, prompt hash and confidence cap.
- Rank: impact `blast × silence / 3` discounted to a quarter at reach 1; effort derived from files, call sites, boundary crossings and test presence; noisy-OR clusters; coverage counted; stale rankings refused.
- Report: one self-contained HTML file plus JSON. Shape, curve with an impact-for-effort ladder (50/70/80%), quadrant, top five, verification, batch plan, all findings, could-not-determine. Secrets redacted before publication.
- Verify: probes in a git worktree or a copy; `reproduced` for a defect, `fixed` only on red-to-green with `--fix`; `--scaffold` writes templates and refuses unfilled ones.
- Calibrate: deterministic stratified sample, precision per taxonomy, `incomplete` under 20 filled rows.
- Known limits: reachability is file-level; JS/TS bounds are regex-based; redaction is pattern-based; the skill has not audited a real repository yet, and phase-2 precision is unmeasured until `calibrate` is filled in.
