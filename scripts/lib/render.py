"""Single-file HTML report. No JS, no CDN, no fonts. Opens from file://."""

import re
from html import escape as _escape

MAX_ROWS = 500

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       max-width: 900px; margin: 0 auto; padding: 40px 24px 80px; color: #1c1c1e; background: #fff; }
h1 { font-size: 27px; margin: 0 0 4px; letter-spacing: -0.02em; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b6b70;
     margin: 40px 0 12px; border-bottom: 1px solid #e6e6e8; padding-bottom: 6px; }
.sub { color: #6b6b70; margin: 0 0 24px; font-size: 14px; }
.verdict { font-size: 18px; line-height: 1.5; border-left: 3px solid #1c1c1e; padding: 4px 0 4px 16px; }
.verdict.flat { border-color: #b25000; }
.verdict.shortcut { border-color: #0a7d33; }
table { width: 100%; border-collapse: collapse; font-size: 14px; margin: 8px 0 4px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #ececee; vertical-align: top; }
th { font-weight: 600; color: #4a4a4f; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.card { border: 1px solid #e6e6e8; border-radius: 8px; padding: 14px 16px; margin: 0 0 12px; }
.card h3 { margin: 0 0 6px; font-size: 16px; }
.card .why { margin: 0 0 8px; }
code { font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; background: #f4f4f6;
       padding: 1px 5px; border-radius: 4px; overflow-wrap: anywhere; }
.meta { color: #6b6b70; font-size: 13px; }
.badge { display: inline-block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
         padding: 2px 7px; border-radius: 999px; background: #eeeef1; color: #4a4a4f; margin-right: 6px; }
.badge.high { background: #e6f4ea; color: #0a6b2c; }
.badge.med { background: #fdf0dd; color: #8a5300; }
.badge.low { background: #f2f2f4; color: #5a5a60; }
.note { background: #fafaf7; border: 1px solid #eaeae4; border-radius: 8px; padding: 12px 16px; font-size: 14px; }
ul { margin: 8px 0; padding-left: 20px; }
li { margin: 4px 0; }
.warn { color: #8a5300; }
"""

VERDICT_TEXT = {
    "shortcut":
        "Impact is concentrated: the top {top_n} of {n} clusters carry {pct} of it, and they are small fixes. "
        "There is a shortcut here.",
    "concentrated-expensive":
        "Impact is concentrated — the top {top_n} of {n} clusters carry {pct} of it — but those fixes are large. "
        "The risk is concentrated; the work is not cheap.",
    "moderate":
        "No clean cutoff: the top {top_n} of {n} clusters carry {pct} of the impact. "
        "Use an effort budget rather than a fixed set.",
    "flat":
        "No shortcut. Impact is spread across {n} clusters — effort tracks impact almost linearly. "
        "Fixing a few will not move the needle.",
    "empty": "No findings. That is a result, not an error — but see what could not be determined.",
}


def _slug(value):
    return re.sub(r"[^A-Za-z0-9._:-]+", "-", str(value)).strip("-") or "x"


def _e(value):
    return _escape(str(value), quote=True)


def verdict_sentence(shape_info):
    template = VERDICT_TEXT.get(shape_info["verdict"], VERDICT_TEXT["empty"])
    return template.format(
        top_n=shape_info.get("top_n", 0),
        n=shape_info.get("n_clusters", 0),
        pct="%.0f%%" % (100 * shape_info.get("c20", 0.0)),
    )


def render(ranked, scope):
    shape_info = ranked["shape"]
    quadrant = ranked["quadrant"]
    clusters = ranked["clusters"]
    findings = {f["id"]: f for f in ranked["findings"]}
    curve = ranked["curve"]

    out = []
    out.append("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">")
    out.append("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
    out.append("<title>pareto-triage report — %s</title>" % _e(ranked["repo_name"]))
    out.append("<style>%s</style></head><body>" % CSS)

    out.append("<h1>pareto-triage — %s</h1>" % _e(ranked["repo_name"]))
    if ranked.get("stale"):
        out.append("<p class=\"verdict flat\">STALE — %s</p>"
                   % _e("; ".join(ranked["stale"].get("reasons") or ["ranking does not match the tree"])))
    if ranked.get("confidence_cap"):
        out.append("<p class=\"meta\">Confidence capped at <strong>%s</strong> — %s</p>"
                   % (_e(ranked["confidence_cap"]), _e(ranked.get("confidence_cap_reason") or "")))
    prompt = ranked.get("prompt") or {}
    prompt_note = ""
    if prompt.get("hash"):
        prompt_note = " · prompt %s" % prompt["hash"]
    out.append("<p class=\"sub\">%d findings, %d clusters · tool %s%s · scan of %s</p>"
               % (len(findings), len(clusters), _e(ranked["tool_version"]),
                  _e(prompt_note), _e(ranked["generated_at"])))

    # 1. Shape
    out.append("<h2>Shape</h2>")
    out.append("<p class=\"verdict %s\">%s</p>" % (_e(shape_info["verdict"]),
                                                   _e(verdict_sentence(shape_info))))

    # 2. Curve
    out.append("<h2>Curve — cumulative impact per unit of effort</h2>")
    out.append("<table><thead><tr><th>#</th><th>Cluster</th>"
               "<th class=\"num\">Cumulative impact</th><th class=\"num\">Cumulative effort</th></tr></thead><tbody>")
    for index, row in enumerate(curve, start=1):
        out.append("<tr><td class=\"num\">%d</td><td><code>%s</code></td>"
                   "<td class=\"num\">%.0f%%</td><td class=\"num\">%.1f</td></tr>"
                   % (index, _e(row["key"]), 100 * row["cum_impact_share"], row["cum_effort"]))
    out.append("</tbody></table>")

    markers = ranked.get("curve_markers")
    if markers is None:
        from .score import curve_markers as _curve_markers
        markers = _curve_markers(clusters)
    reached = [m for m in markers if m.get("reached")]
    if reached:
        sentence = "; ".join("at %g effort units → %.0f%% of weighted impact"
                             % (m["budget"], 100 * m["cum_impact_share"]) for m in reached)
        out.append("<p>%s.</p>" % _e(sentence))
    for marker in markers:
        if not marker.get("reached"):
            out.append("<p class=\"meta\">Budget %s (%g effort units) is not reached: the whole set "
                       "costs %.1f units.</p>"
                       % (_e(marker["label"]), marker["budget"],
                          markers[-1]["cum_effort"] if markers else 0.0))
            break
    pareto = ranked.get("pareto") or {}
    ladder = ranked.get("pareto_ladder") or []
    if ladder:
        rows = [row for row in ladder if row.get("effort_share") is not None]
        if rows:
            out.append("<table><thead><tr><th>Impact covered</th><th class=\"num\">Clusters</th>"
                       "<th class=\"num\">Share of effort</th></tr></thead><tbody>")
            for row in rows:
                out.append("<tr><td class=\"num\">%.0f%%</td><td class=\"num\">%d of %d</td>"
                           "<td class=\"num\">%.0f%%</td></tr>"
                           % (100 * row["target"], row["clusters"], row["of_clusters"],
                              100 * row["effort_share"]))
            out.append("</tbody></table>")
    if pareto and pareto.get("effort_share") is not None:
        if pareto.get("shortcut"):
            out.append("<p class=\"key\">%d of %d clusters carry %.0f%% of the impact for %.0f%% of the effort.</p>"
                       % (pareto["clusters"], pareto["of_clusters"], 100 * pareto["target"],
                          100 * pareto["effort_share"]))
        else:
            out.append("<p class=\"meta\">%.0f%% of the impact costs %.0f%% of the effort — "
                       "no cheap set, the work tracks the benefit.</p>"
                       % (100 * pareto["target"], 100 * pareto["effort_share"]))
    out.append("<p class=\"meta\">Effort units are the rubric's ordinal bands summed, not hours. "
               "A flat curve is a finding, not a failure of the tool.</p>")

    # 3. Quadrant
    out.append("<h2>Quadrant</h2>")
    out.append("<table><thead><tr><th></th><th class=\"num\">Low effort</th><th class=\"num\">High effort</th></tr></thead><tbody>")
    out.append("<tr><th>High impact</th><td class=\"num\">%d do now</td><td class=\"num\">%d schedule</td></tr>"
               % (quadrant["counts"]["quick_wins"], quadrant["counts"]["batch_2"]))
    out.append("<tr><th>Low impact</th><td class=\"num\">%d anytime</td><td class=\"num\">%d ignore</td></tr>"
               % (quadrant["counts"]["free"], quadrant["counts"]["skip"]))
    out.append("</tbody></table>")

    # 4. Top five
    verification_by_cluster = {}
    for record in (ranked.get("verification") or {}).get("clusters") or []:
        verification_by_cluster[record.get("cluster")] = record

    out.append("<h2>Top five</h2>")
    if not clusters:
        out.append("<p class=\"meta\">Nothing to rank.</p>")
    for cluster in clusters[:5]:
        sample = findings.get(cluster["findings"][0], {})
        proof = verification_by_cluster.get(cluster["key"])
        out.append("<div class=\"card\">")
        out.append("<h3>%s</h3>" % _e(cluster["message"] or cluster["key"]))
        out.append("<p class=\"why\"><a href=\"#f-%s\"><code>%s:%s</code></a> · %s · %d site%s</p>"
                   % (_e(_slug(sample.get("id", ""))), _e(sample.get("file", "")),
                      _e(sample.get("line", "")), _e(cluster["taxonomy"]), cluster["n_sites"],
                      "" if cluster["n_sites"] == 1 else "s"))
        out.append("<p><code>%s</code></p>" % _e(sample.get("evidence", "")))

        capped = bool(sample.get("confidence_capped"))
        confidence = sample.get("confidence") or "med"
        if capped and sample.get("confidence_reason"):
            confidence_note = "%s confidence (capped: %s)" % (confidence, sample["confidence_reason"])
        elif capped:
            confidence_note = "%s confidence (capped)" % confidence
        elif cluster.get("class") == "defect":
            confidence_note = "%s confidence (tool detector)" % confidence
        else:
            confidence_note = "%s confidence (model)" % confidence

        badges = ["<span class=\"badge%s\">%s</span>"
                  % ("" if confidence == "high" else " high", _e(confidence_note)),
                  "<span class=\"badge\">impact %.1f</span>" % cluster["impact"],
                  "<span class=\"badge\">effort %.1f</span>" % cluster["effort"],
                  "<span class=\"badge\">priority %.2f</span>" % cluster["priority"]]
        if proof and proof.get("status") == "fixed":
            badges.append("<span class=\"badge high\">fixed: red → green</span>")
        elif proof and proof.get("status") == "reproduced":
            badges.append("<span class=\"badge high\">reproduced</span>")
        elif proof and proof.get("status") == "not-reproduced":
            badges.append("<span class=\"badge\">probe passed</span>")
        elif proof and proof.get("status") == "inconclusive":
            badges.append("<span class=\"badge\">inconclusive</span>")
        out.append("<p class=\"meta\">%s</p>" % "".join(badges))

        drivers = sample.get("effort_drivers") or []
        out.append("<p class=\"meta\">%s</p>"
                   % _e("effort drivers: " + (", ".join(drivers) if drivers else "unavailable")))
        out.append("</div>")

    # 5. Verification
    verification = ranked.get("verification")
    out.append("<h2>Verification</h2>")
    if not verification:
        out.append("<p class=\"meta\">Not run. No claim in this report has been reproduced by an "
                   "executable test. Run <code>pareto-triage verify</code> and add probes under "
                   "<code>out/probes/</code>.</p>")
    else:
        counts = verification.get("counts") or {}
        fix = verification.get("fix") or {}
        out.append("<p class=\"meta\">%d of %d top clusters reproduced by an executable probe; "
                   "%d moved from red to green after a patch. Reproduced means the defect is real; "
                   "fixed means this test passed afterwards, not that the patch is correct.</p>"
                   % (counts.get("reproduced", 0) + counts.get("fixed", 0),
                      len(verification.get("clusters") or []), counts.get("fixed", 0)))
        out.append("<table><thead><tr><th>Cluster</th><th>Status</th><th>Probe</th>"
                   "<th class=\"num\">Exit</th><th>Note</th></tr></thead><tbody>")
        for record in verification.get("clusters") or []:
            out.append("<tr><td><code>%s</code></td><td>%s</td><td><code>%s</code></td>"
                       "<td class=\"num\">%s</td><td class=\"meta\">%s</td></tr>"
                       % (_e(record.get("cluster")), _e(record.get("status")),
                          _e(record.get("probe") or "—"),
                          "—" if record.get("exit") is None else record.get("exit"),
                          _e(record.get("reason") or "")))
        out.append("</tbody></table>")
        suite = verification.get("suite") or {}
        out.append("<p class=\"meta\">Project suite: %s%s</p>"
                   % (_e(suite.get("status", "unknown")),
                      "" if not suite.get("command") else " — <code>%s</code>" % _e(suite["command"])))

    # 6. Batch plan
    out.append("<h2>Batch plan</h2>")
    out.append("<table><thead><tr><th>Batch</th><th class=\"num\">Findings</th><th>What it means</th></tr></thead><tbody>")
    out.append("<tr><td>Do now</td><td class=\"num\">%d</td><td>High impact, low effort. Start here.</td></tr>"
               % quadrant["counts"]["quick_wins"])
    out.append("<tr><td>Schedule</td><td class=\"num\">%d</td><td>High impact, high effort. Needs a slot.</td></tr>"
               % quadrant["counts"]["batch_2"])
    out.append("<tr><td>Anytime</td><td class=\"num\">%d</td><td>Cheap and low impact. Fill gaps.</td></tr>"
               % quadrant["counts"]["free"])
    out.append("<tr><td>Ignore</td><td class=\"num\">%d</td><td>Expensive and low impact. Record, defer, forget.</td></tr>"
               % quadrant["counts"]["skip"])
    out.append("</tbody></table>")

    # 7. All findings
    out.append("<h2>All findings</h2>")
    grouped = []
    seen_findings = set()
    for cluster in clusters:
        rows = [findings[item] for item in cluster["findings"] if item in findings]
        seen_findings.update(cluster["findings"])
        if rows:
            grouped.append((cluster, rows))
    leftover = [f for f in ranked["findings"] if f["id"] not in seen_findings]
    if leftover:
        grouped.append(({"key": "unclustered", "impact": 0.0, "effort": 0.0,
                         "priority": 0.0, "n_sites": len(leftover)}, leftover))

    out.append("<div class=\"note\"><ul>")
    for cluster, rows in grouped:
        out.append("<li><a href=\"#c-%s\"><code>%s</code></a> — %d finding%s</li>"
                   % (_e(_slug(cluster["key"])), _e(cluster["key"]), len(rows),
                      "" if len(rows) == 1 else "s"))
    out.append("</ul></div>")

    shown = 0
    total_rows = sum(len(rows) for _, rows in grouped)
    for cluster, rows in grouped:
        out.append("<h3 id=\"c-%s\"><code>%s</code> — impact %.1f, effort %.1f</h3>"
                   % (_e(_slug(cluster["key"])), _e(cluster["key"]),
                      cluster["impact"], cluster["effort"]))
        out.append("<table><thead><tr><th>Id</th><th>Finding</th><th>Where</th>"
                   "<th class=\"num\">Reach</th><th class=\"num\">Blast</th>"
                   "<th class=\"num\">Silence</th><th class=\"num\">Effort</th>"
                   "<th class=\"num\">Impact</th></tr></thead><tbody>")
        for f in sorted(rows, key=lambda x: (-x["priority"], x["file"], x["line"])):
            if shown >= MAX_ROWS:
                break
            shown += 1
            out.append("<tr id=\"f-%s\"><td><a href=\"#f-%s\"><code>%s</code></a></td>"
                       "<td><code>%s</code><br><span class=\"meta\">%s</span></td>"
                       "<td><code>%s:%s</code></td><td class=\"num\">%d</td>"
                       "<td class=\"num\">%d</td><td class=\"num\">%d</td>"
                       "<td class=\"num\">%d</td><td class=\"num\">%.2f</td></tr>"
                       % (_e(_slug(f["id"])), _e(_slug(f["id"])), _e(f["id"]),
                          _e(f["taxonomy"]), _e(f.get("message", "")),
                          _e(f["file"]), _e(f["line"]), f["reach"], f["blast"],
                          f["silence"], f["effort"], f["impact"]))
        out.append("</tbody></table>")
        if shown >= MAX_ROWS:
            break

    if total_rows > shown:
        out.append("<p class=\"meta\">Showing %d of %d findings. The rest are in "
                   "<code>report.json</code>, which is the primary artifact.</p>"
                   % (shown, total_rows))

    # 8. Could not determine
    out.append("<h2>Could not determine</h2>")
    redactions = ranked.get("redactions") or []
    if redactions:
        items = ", ".join("%s:%s (%s)" % (r.get("file"), r.get("line"), r.get("rule"))
                          for r in redactions[:10])
        more = "" if len(redactions) <= 10 else ", … %d more" % (len(redactions) - 10)
        out.append("<div class=\"note\"><p>%d secret(s) redacted in the published evidence: %s%s. "
                   "The unredacted line remains in <code>out/defects.jsonl</code>.</p></div>"
                   % (sum(r.get("count", 1) for r in redactions), _e(items), _e(more)))
    calibration = ranked.get("calibration") or {}
    if calibration:
        out.append("<div class=\"note\"><p>Phase 2 precision: %s of %s sampled findings correct "
                   "(threshold %.2f) — <strong>%s</strong>. %s</p></div>"
                   % (_e(calibration.get("precision")), _e(calibration.get("filled")),
                      calibration.get("threshold", 0.7), _e(calibration.get("status")),
                      _e(calibration.get("note", ""))))
    coverage = ranked.get("coverage") or {}
    if coverage.get("sites_total") is not None:
        out.append("<div class=\"note\"><p>Phase 2 judged %d of %d candidate sites; %d were not assessed. "
                   "A site that was never judged is not a site that was found clean.</p></div>"
                   % (coverage.get("sites_judged") or 0, coverage["sites_total"],
                      coverage.get("sites_unjudged") or 0))
    unproven = ranked.get("unproven") or []
    if unproven:
        out.append("<h3>Unproven — supplied, could not be scored</h3>")
        out.append("<table><thead><tr><th>Where</th><th>Taxonomy</th><th>Why</th></tr>"
                   "</thead><tbody>")
        for record in unproven[:50]:
            out.append("<tr><td><code>%s:%s</code></td><td>%s</td>"
                       "<td class=\"meta\">%s</td></tr>"
                       % (_e(record.get("file")), _e(record.get("line")),
                          _e(record.get("taxonomy") or record.get("class")),
                          _e(record.get("reason"))))
        out.append("</tbody></table>")
        if len(unproven) > 50:
            out.append("<p class=\"meta\">… %d more in <code>report.json</code>.</p>"
                       % (len(unproven) - 50))
        out.append("<p class=\"meta\">These carry no score on purpose: a claim without "
                   "verifiable evidence is listed, not ranked.</p>")
    out.append("<div class=\"note\"><ul>")
    for item in ranked["could_not_determine"]:
        out.append("<li>%s</li>" % _e(item))
    out.append("</ul></div>")

    out.append("<p class=\"meta\" style=\"margin-top:32px\">This report measures code, not people. "
               "It ranks risk; it does not diagnose root cause. Every number here is reproducible from "
               "the accompanying JSON and the published rubric.</p>")
    out.append("</body></html>")
    return "\n".join(out)
