"""Scoring, clustering, and shape. Pure functions; no I/O."""

import math
import statistics


REACH_DISCOUNT = {1: 0.25}

# C20 is an impact share of the top fifth of clusters. Below three clusters
# that fifth is one cluster and the share is arithmetic, not evidence: with a
# single cluster it is 1.0 by construction, so the report must not call it a
# shortcut. Three is the smallest count where "the top fifth" leaves anything
# out of the comparison.
MIN_CLUSTERS_FOR_VERDICT = 3


def annotate(findings):
    """Apply the rubric's reach discount, then impact and priority."""
    for f in findings:
        impact = (f["blast"] * f["silence"]) / 3.0
        factor = REACH_DISCOUNT.get(f.get("reach"))
        if factor is not None:
            impact *= factor
            f["reach_discount"] = factor
        f["impact"] = round(impact, 4)
        f["priority"] = round(f["impact"] / f["effort"], 4)
    return findings


def cluster_key(finding):
    return finding.get("rule") or finding.get("taxonomy")


def cluster_findings(findings):
    groups = {}
    for f in findings:
        groups.setdefault(cluster_key(f), []).append(f)

    clusters = []
    for key, items in groups.items():
        survival = 1.0
        for item in items:
            survival *= 1.0 - item["impact"] / 5.0
        # Noisy-OR in normalised space, scaled back to the 0-5 impact axis so
        # cluster and finding numbers are comparable in the report.
        impact = 5.0 * (1.0 - survival)

        efforts = sorted(item["effort"] for item in items)
        representative = efforts[len(efforts) // 2]
        effort = min(representative * (1 + 0.4 * (len(items) - 1)), float(sum(efforts)))

        clusters.append({
            "key": key,
            "taxonomy": items[0]["taxonomy"],
            "class": items[0]["class"],
            "n_sites": len(items),
            "impact": round(impact, 4),
            "effort": round(effort, 2),
            "priority": round(impact / effort, 4) if effort else 0.0,
            "findings": [item["id"] for item in items],
            "message": items[0].get("message"),
            "file": items[0]["file"],
            "line": items[0]["line"],
        })

    clusters.sort(key=lambda c: (-c["priority"], c["key"]))
    return clusters


def shape(clusters):
    """C20: impact share of the top 20% of clusters, sorted by impact alone.

    Below MIN_CLUSTERS_FOR_VERDICT the share is arithmetic rather than
    evidence, so the verdict is `insufficient` and c20 is still reported.
    """
    if not clusters:
        return {
            "c20": 0.0,
            "verdict": "empty",
            "n_clusters": 0,
            "min_clusters": MIN_CLUSTERS_FOR_VERDICT,
            "top_n": 0,
            "top_median_effort": 0.0,
            "top_keys": [],
        }

    total = sum(c["impact"] for c in clusters)
    by_impact = sorted(clusters, key=lambda c: -c["impact"])
    top_n = max(1, math.ceil(0.2 * len(by_impact)))
    top = by_impact[:top_n]
    c20 = (sum(c["impact"] for c in top) / total) if total else 0.0
    median_effort = sorted(c["effort"] for c in top)[len(top) // 2]

    if len(by_impact) < MIN_CLUSTERS_FOR_VERDICT:
        verdict = "insufficient"
    elif c20 >= 0.6:
        verdict = "shortcut" if median_effort <= 2.5 else "concentrated-expensive"
    elif c20 >= 0.3:
        verdict = "moderate"
    else:
        verdict = "flat"

    return {
        "c20": round(c20, 3),
        "verdict": verdict,
        "n_clusters": len(clusters),
        "min_clusters": MIN_CLUSTERS_FOR_VERDICT,
        "top_n": top_n,
        "top_median_effort": median_effort,
        "top_keys": [c["key"] for c in top],
    }


CLASS_LABELS = (("defect", "defect"), ("failure-mode", "failure_mode"))


def attribution(clusters, shape_info=None):
    """Impact by finding class, both overall and inside the C20 top set.

    The verdict is a property of the cluster set, not of one detector. When the
    top fifth is one rule cluster, the concentration is a rule result and must
    not be reported as a model conclusion. `share` is of total impact; the
    nested `top.share` is of the top-set impact, so it is the share of C20 that
    the class carries.
    """
    info = shape_info if shape_info is not None else shape(clusters)
    top_keys = set(info.get("top_keys") or [])
    if not top_keys and clusters:
        top_n = max(1, math.ceil(0.2 * len(clusters)))
        top_keys = {c["key"] for c in sorted(clusters, key=lambda c: -c["impact"])[:top_n]}

    total = sum(c["impact"] for c in clusters)
    top_total = sum(c["impact"] for c in clusters if c["key"] in top_keys)

    block = {}
    for class_name, block_name in CLASS_LABELS:
        items = [c for c in clusters if c.get("class") == class_name]
        top_items = [c for c in items if c["key"] in top_keys]
        impact = sum(c["impact"] for c in items)
        top_impact = sum(c["impact"] for c in top_items)
        block[block_name] = {
            "clusters": len(items),
            "findings": sum(c.get("n_sites", 0) for c in items),
            "impact": round(impact, 4),
            "share": round(impact / total, 3) if total else 0.0,
            "top": {
                "clusters": len(top_items),
                "impact": round(top_impact, 4),
                "share": round(top_impact / top_total, 3) if top_total else 0.0,
            },
            "verdict": shape(items)["verdict"],
        }

    block["c20"] = info.get("c20", 0.0)
    block["top_n"] = info.get("top_n", 0)
    block["top_impact"] = round(top_total, 4)
    return block


DEFAULT_BUDGETS = (5, 15, 30)
BUDGET_LABELS = ("S", "M", "L")


def curve_markers(clusters, budgets=DEFAULT_BUDGETS):
    """Impact share reached at each effort budget. Effort units, never hours."""
    ordered = sorted(clusters, key=lambda c: -c["priority"])
    total_impact = sum(c["impact"] for c in ordered)

    markers = []
    cum_impact = 0.0
    cum_effort = 0.0
    index = 0
    for label, budget in zip(BUDGET_LABELS, budgets):
        while index < len(ordered) and cum_effort < budget:
            cum_impact += ordered[index]["impact"]
            cum_effort += ordered[index]["effort"]
            index += 1
        reached = cum_effort >= budget
        markers.append({
            "label": label,
            "budget": budget,
            "reached": reached,
            "cum_effort": round(cum_effort, 1),
            "cum_impact_share": round(cum_impact / total_impact, 3) if total_impact else 0.0,
        })
    return markers


def pareto_point(clusters, target=0.8):
    """The cheapest set that covers `target` of the impact, as an effort share.

    Answers "80% of the impact costs what fraction of the work?" — 12% when the
    bet holds, 63% when it does not. Never claims a shortcut that is not there.
    """
    ordered = sorted(clusters, key=lambda c: -c["priority"])
    total_impact = sum(c["impact"] for c in ordered)
    total_effort = sum(c["effort"] for c in ordered)
    if not ordered or total_impact <= 0 or total_effort <= 0:
        return {"target": target, "shortcut": False, "clusters": 0,
                "effort_share": None, "impact_share": 0.0}

    cum_impact = 0.0
    cum_effort = 0.0
    for index, cluster in enumerate(ordered, start=1):
        cum_impact += cluster["impact"]
        cum_effort += cluster["effort"]
        if cum_impact / total_impact >= target:
            share = cum_effort / total_effort
            return {
                "target": target,
                "shortcut": share <= 0.5,
                "clusters": index,
                "of_clusters": len(ordered),
                "effort_share": round(share, 3),
                "impact_share": round(cum_impact / total_impact, 3),
            }

    return {"target": target, "shortcut": False, "clusters": len(ordered),
            "of_clusters": len(ordered), "effort_share": 1.0,
            "impact_share": round(cum_impact / total_impact, 3)}


def pareto_ladder(clusters, targets=(0.5, 0.7, 0.8)):
    """Impact covered against effort spent, at several targets.

    The 80/20 bet is the headline, but a repo can still have a best set: 10% of
    the effort for 50% of the impact is a real answer even when 80% costs 60%.
    """
    return [pareto_point(clusters, target) for target in targets]


def quadrant(findings):
    if not findings:
        return {"median_impact": 0.0, "median_effort": 0.0,
                "counts": {"quick_wins": 0, "batch_2": 0, "free": 0, "skip": 0}, "ids": {}}

    median_impact = statistics.median(f["impact"] for f in findings)
    median_effort = statistics.median(f["effort"] for f in findings)

    buckets = {"quick_wins": [], "batch_2": [], "free": [], "skip": []}
    for f in findings:
        high_impact = f["impact"] >= median_impact
        cheap = f["effort"] <= median_effort
        if high_impact and cheap:
            buckets["quick_wins"].append(f["id"])
        elif high_impact:
            buckets["batch_2"].append(f["id"])
        elif cheap:
            buckets["free"].append(f["id"])
        else:
            buckets["skip"].append(f["id"])

    return {
        "median_impact": median_impact,
        "median_effort": median_effort,
        "counts": {k: len(v) for k, v in buckets.items()},
        "ids": buckets,
    }


def coverage_curve(clusters):
    ordered = sorted(clusters, key=lambda c: -c["priority"])
    total_impact = sum(c["impact"] for c in ordered)
    total_effort = sum(c["effort"] for c in ordered)

    rows = []
    cum_impact = 0.0
    cum_effort = 0.0
    for cluster in ordered:
        cum_impact += cluster["impact"]
        cum_effort += cluster["effort"]
        rows.append({
            "key": cluster["key"],
            "cum_impact_share": round(cum_impact / total_impact, 3) if total_impact else 0.0,
            "cum_effort": round(cum_effort, 1),
            "cum_effort_share": round(cum_effort / total_effort, 3) if total_effort else 0.0,
        })
    return rows
