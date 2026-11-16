# Changelog

## 0.1.0

First release.

- Scan: `gate` refuses a repo where a ranking would be invented; `context` emits one record per function reachable from an entrypoint; `detect` runs 22 rules, secrets included; `validate` enforces verbatim evidence, site correspondence, prompt hash and confidence cap.
- Rank: impact `blast × silence / 3` discounted to a quarter at reach 1; effort derived from files, call sites, boundary crossings and test presence; noisy-OR clusters; coverage counted; stale rankings refused.
- Report: one self-contained HTML file plus JSON. Shape, curve with an impact-for-effort ladder (50/70/80%), quadrant, top five, verification, batch plan, all findings, could-not-determine. Secrets redacted before publication.
- Verify: probes in a git worktree or a copy; `reproduced` for a defect, `fixed` only on red-to-green with `--fix`; `--scaffold` writes templates and refuses unfilled ones.
- Calibrate: deterministic stratified sample, precision per taxonomy, `incomplete` under 20 filled rows.
- Known limits: reachability is file-level; JS/TS bounds are regex-based; redaction is pattern-based; the skill has not audited a real repository yet, and phase-2 precision is unmeasured until `calibrate` is filled in.
