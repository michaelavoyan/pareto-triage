# Report format

Fixed section order. A reader must be able to stop after section 1 and still know something true.

## 1. Shape

One sentence, no numbers without context:

> Impact is concentrated: 22% of clusters carry 71% of it, and four of those six are small fixes. There is a shortcut here.

or

> No shortcut. Impact is spread across 31 unrelated findings; effort tracks impact almost linearly. Fixing a few will not move the needle.

## 2. Curve

Cumulative impact vs cumulative effort, plus a ladder answering one question at three heights: what share of the total effort buys 50%, 70%, 80% of the impact, and how many clusters that is. The 80% row is the Pareto headline when it is cheap; the 50% and 70% rows are the answer when it is not. A reader must never be left with only "no shortcut".

Also markers at S / M / L budget points. Budgets are effort units — 5, 15, 30 by default, overridable with `--budget`. Text, not a chart: "at 5 effort units → 41% of weighted impact; at 15 → 68%". When a budget exceeds the whole set, say so: "L (30) is not reached: the whole set costs 22 units."

Never show a percentage without the tool version that produced it.

## 3. Quadrant

Four cells with counts, not lists: do-now / schedule / anytime / ignore. The counts are the message.

## 4. Top 5

Per item:

- **What breaks** — plain language, one sentence, no jargon. "Stripe retries are charged twice."
- **Evidence** — quoted line, `file:line` linking to the finding's row in §7.
- **Counter-evidence** — the sentence you owe the reader.
- **Effort** — band plus drivers, printed as measured ("1 file, 0 importers"), or "unavailable" when they were not computed. Never a plausible constant.
- **Confidence** — high / med / low, and why: "(capped: no test runner detected)", "(tool detector)", "(model)".
- **Verified** — badge only if a probe ran and failed, i.e. the defect reproduced.

## 5. Verification

Present always. Two states, both honest:

- **Not run** — one line saying no claim in the report has been reproduced by an executable test, and where probes go (`out/probes/<cluster>.<ext>`).
- **Run** — how many of the top clusters reproduced, a table of cluster / status / probe / exit / note, and the project suite's status.

`reproduced` means a test failed because of the defect. `fixed` means the same test passed after a patch — red to green — and even that only says the patch works for this test, not that it is correct. Both limits are stated in the section. `inconclusive` means the probe still failed after the patch, or the probe was already green. `unverified` is a legitimate outcome, not a gap to paper over.

## 6. Batch plan

Four batches — do now, schedule, anytime, ignore — each with what it buys in counts: "Do now: closes 4 of 5 silent-failure paths." Not percentages. Batches are schedulable; "the 20%" is not.

## 7. All findings

Grouped by cluster, each group anchored, each row carrying its finding id as an anchor so a reader can link to it. Every id exists in `report.json`. Static file: no sorting controls, because the spec forbids JavaScript and an unsortable table is honest about it. Long reports show the first 500 rows and point at `report.json`.

## 8. Could not determine

Mandatory, never empty. Always include:

- reachability gaps (dynamic dispatch, DI, monorepo aliases)
- languages or files skipped, with reasons and counts
- how phase 2's sites were chosen: when `out/sample.json` exists, its `mode` and `seed`, sites kept of the population, and the per-file cap, with the sentence that rule findings cover every file and the sample bounds judgment only. A site outside the sample was not judged, and is not clean
- suspected-but-unprovable findings, listed without scores — the "Unproven" table: a supplied record that failed the evidence guard, cited a site that does not exist, or came from another prompt. It carries `file:line`, its taxonomy, and the reason. No impact, no effort, no priority
- secret redactions performed and where: every masked quote, with `file:line` and the rule that masked it

If the honest answer is "everything was measurable", say which checks you ran to establish that.

## Rules

- Every claim cites a line or an artifact. No exceptions.
- No gauges, radar charts, letter grades, or bare scores.
- Single self-contained HTML file: no CDN, no external fonts, no JS required to read, opens from `file://`.
- The JSON is the primary artifact; the HTML is a rendering of it.
- Never state "80/20", "the Pareto set", or a guarantee. State the measured shape.
- Never rank people. State once, plainly, that this measures code.
