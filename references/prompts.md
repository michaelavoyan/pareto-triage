# Enrichment prompts and schema

The hash is the version. It is derived from the prompt text below, so it cannot drift from it; two reports carrying different hashes were produced by different prompts and are not comparable.

The hash is computed from the fenced prompt below plus the category list, with whitespace normalised, and pinned in `ranked.json` as `prompt: {version, hash}` and in the report subtitle. `validate` refuses records stamped with another hash, and `rank` refuses them again, because a mixed-prompt ranking is not a measurement.

## Input

`out/context.jsonl` — one record per candidate site. Produced by `pareto-triage context`; do not assemble it by hand. Records may carry `truncated: true` when the function body exceeded the line cap.

```jsonc
{
  "site_id": "s_001",
  "file": "src/payments/webhook.ts",
  "function": "handleWebhook",
  "lines": [120, 180],
  "lang": "ts",
  "reach": 5,
  "call_path": ["POST /webhooks/stripe", "src/payments/webhook.ts", "handleWebhook"],
  "source": "<the function body, verbatim>",
  "surrounding": "<imports, client config, middleware chain>",
  "truncated": false
}
```

`call_path` is file-level: the entrypoint, then each file the import path crosses, then the function. It does not name intermediate callers.

## Prompt

```
You are auditing one function for production failure modes. You have the function
body, its call path from an entrypoint, and its surrounding configuration.

Apply ONLY these categories:
swallowed-exception, missing-timeout, no-retry, no-backoff, missing-idempotency,
unbounded-query, unbounded-concurrency, missing-boundary-validation, missing-authz,
silent-default-fallback, resource-leak, non-atomic-write, missing-cancellation

For each category that applies, return an object with:
  taxonomy        one of the above, exact spelling
  file, line      the line number where the problem is visible
  evidence        a verbatim quote from the source. Not a paraphrase. 1-3 lines.
  counter_evidence  one sentence: why this might genuinely be fine here
  blast           0-5, consequence if it fires
  silence         1-3, how quietly it fails

Rules:
- No evidence, no finding. If you cannot quote it, it does not exist.
- No counter_evidence, no finding. If you cannot say why it might be fine,
  you have not understood the code.
- Do not report style, naming, dead code, or missing tests.
- Do not infer runtime behaviour you cannot see in the source.
- Return [] if nothing applies. An empty result is a correct result.
```

Run one call per site. Do not batch sites into one prompt — cross-contamination produces findings attributed to the wrong file.

## Output schema (`out/failure-modes.jsonl`)

```jsonc
{
  "id": "f_<8 hex>",
  "site_id": "s_001",
  "class": "failure-mode",
  "taxonomy": "missing-idempotency",
  "file": "src/payments/webhook.ts",
  "line": 142,
  "evidence": "await db.charge.create({ amount: evt.amount })",
  "counter_evidence": "Stripe may guarantee single delivery per event id.",
  "detector": "llm",
  "confidence": "med",
  "prompt": {"hash": "<16 hex, derived from this file>"},
  "reach": 5,
  "blast": 5,
  "silence": 3,
  "call_path": ["POST /webhooks/stripe", "handleWebhook"]
}
```

Validation gates enforced by `pareto-triage validate`:

1. `class` must be `failure-mode`.
2. `taxonomy` must exist in `taxonomy.md`.
3. `evidence`, `file`, `line`, `counter_evidence` must all be present and non-empty.
4. `evidence` must appear in the source file (whitespace-normalised). This is the anti-hallucination check.
5. `reach`, `blast`, `silence` must be inside their ranges. Do not send `effort` — it is derived by `rank` from the rubric, and a record carrying one is rejected.
6. `detector` must be `llm`.
7. `confidence` must be `low` or `med` — the model never earns `high`.

A record failing any gate is rejected with a reason. Do not hand-edit a rejected record to pass; re-read the code.

Two more gates run when `context.jsonl` is present (it is, by default, next to the findings file):

- `site_id` must exist, and `file` must be that site's file. The line must fall inside the site's bounds, and the evidence must appear inside the site's `source` — not merely somewhere in the same file.
- `confidence` must not exceed the gate's cap (`validate --max-confidence`).
- `prompt.hash` must match the current prompt, when the record carries one. A record stamped with another hash is rejected: findings from different prompts are not comparable. A missing hash warns today.

Coverage is not optional context. `rank` records `sites_judged` against `sites_total`, the report states it in "Could not determine", and `rank --require-coverage 0.9` refuses a run that judged too few sites. A site nobody judged is not a clean site.

## Calibration

Before trusting a run, sample 20 findings and check each against the source. Precision below 0.70 means the prompt or the taxonomy is wrong. Tune the prompt, not the threshold.

`pareto-triage calibrate <repo>` does the sampling: deterministic for a given `--seed`, stratified across taxonomies, written to `out/calibration.jsonl` with an empty `verdict` on each row. Fill `true`/`false`, run it again, and it writes `out/calibration.json` with precision overall and per taxonomy. Under 20 filled rows it reports `incomplete` rather than a misleading number, and the report prints the result in "Could not determine".
