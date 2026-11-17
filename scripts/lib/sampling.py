"""Does the ranked site ordering beat a random sample? Mechanics only.

`context --sample-order ranked` picks sites by reach, inbound edges, body
size, and path. Nothing here assumes that order finds the sites worth judging:
take the selected sites, take a seeded random sample of the same size from the
same population, and compare how often each contains a built-in rule finding.
On Signal-Android at 5,000 sites per arm the two were indistinguishable, which
is why a random sample is now the default.

This module measures containment only. It does not judge severity, impact, or
whether a site is worth fixing, and it never counts a phase-2 failure mode:
those are model judgments, not mechanical findings.
"""

import bisect
import math
import random

Z_95 = 1.959963984540054
DEFAULT_LIMIT = 400
DEFAULT_SEED = 0

MEASURE = (
    "mechanically detected rule findings only: a site counts when its file "
    "contains at least one rule finding, and separately when a rule finding's "
    "line falls inside the site's line range. Phase-2 failure modes are model "
    "judgments and are excluded. This is not a judgment of severity, impact, "
    "or whether a site is worth fixing."
)


def random_sample_indexes(size, sample_size, seed=DEFAULT_SEED):
    """Deterministic indexes of a random sample, in ascending order.

    A partial Fisher-Yates shuffle over ``random.Random(seed).randrange``
    instead of ``random.sample``: the draw then depends only on the Mersenne
    Twister stream, which is stable across Python versions, not on the
    standard library's sample strategy. Same size and seed always give the
    same indexes, so two runs on the same `candidates.jsonl` are comparable.
    """
    if sample_size >= size:
        return list(range(size))
    rng = random.Random(seed)
    pool = list(range(size))
    for position in range(sample_size):
        swap = rng.randrange(position, size)
        pool[position], pool[swap] = pool[swap], pool[position]
    return sorted(pool[:sample_size])


def _line_index(findings):
    """file -> sorted finding lines, for containment checks."""
    by_file = {}
    for finding in findings:
        line = finding.get("line")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            continue
        by_file.setdefault(finding.get("file"), set()).add(line)
    return {name: sorted(lines) for name, lines in by_file.items() if name is not None}


def densities(sites, findings):
    """The two shares this command exists to compare.

    file: the site's file contains at least one finding, anywhere.
    line: at least one finding line falls inside the site's [start, end].
    """
    if not sites:
        return {"file": 0.0, "line": 0.0}

    by_file = _line_index(findings)
    file_hits = 0
    line_hits = 0
    for site in sites:
        lines = by_file.get(site.get("file"))
        if not lines:
            continue
        file_hits += 1
        start, end = site.get("lines") or (0, 0)
        index = bisect.bisect_left(lines, start)
        if index < len(lines) and lines[index] <= end:
            line_hits += 1

    return {"file": file_hits / len(sites), "line": line_hits / len(sites)}


def _difference(selected, random_value, n):
    """Difference, 95% normal-approximation interval, and a verdict."""
    difference = selected - random_value
    variance = 0.0
    if n:
        variance = (selected * (1.0 - selected) + random_value * (1.0 - random_value)) / n
    margin = Z_95 * math.sqrt(max(variance, 0.0))
    low, high = difference - margin, difference + margin
    if low > 0:
        verdict = "ordering beats random"
    elif high < 0:
        verdict = "ordering is worse than random"
    else:
        verdict = "indistinguishable"
    return difference, low, high, verdict


def _block(selected, random_value, n):
    difference, low, high, verdict = _difference(selected, random_value, n)
    return {
        "selected": round(selected, 4),
        "random": round(random_value, 4),
        "ratio": round(selected / random_value, 3) if random_value else None,
        "difference": round(difference, 4),
        "ci95": [round(low, 4), round(high, 4)],
        "verdict": verdict,
    }


def _ids(sites):
    return [site.get("site_id") for site in sites]


def measure(population, findings, limit=DEFAULT_LIMIT, seed=DEFAULT_SEED):
    """Compare the first `limit` sites against a random sample of that size.

    `population` is ordered selected-first by `context --all`; the prefix is
    what `context.jsonl` would have emitted. The random sample is drawn from
    the whole population, so it can include selected sites — that is the point:
    the null hypothesis is that the ordering does not matter.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    n = min(limit, len(population))
    selected_sites = list(population[:n])
    random_indexes = random_sample_indexes(len(population), n, seed)
    random_sites = [population[index] for index in random_indexes]

    selected_density = densities(selected_sites, findings)
    random_density = densities(random_sites, findings)

    file_block = _block(selected_density["file"], random_density["file"], n)
    line_block = _block(selected_density["line"], random_density["line"], n)

    return {
        "limit": limit,
        "seed": seed,
        "population": len(population),
        "n": n,
        "measure": MEASURE,
        "verdict_basis": "file_density",
        "verdict": file_block["verdict"],
        "file_density": file_block,
        "line_density": line_block,
        "sample": {
            "selected": _ids(selected_sites),
            "random": _ids(random_sites),
        },
    }
