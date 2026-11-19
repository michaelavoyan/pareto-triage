"""Effort bands. Ordinal only, never hours.

Two documented formulas live here so neither script can drift from the rubric:

  defect      effort = 1 + no_test + crosses_boundary                     (rubric 1.1)
  failure mode effort = 1 + files/3 + callsites/5 + crosses_boundary + no_test

Both clamp to 1..5. Drivers are measured inputs, never literals: a report that
says "1 file" must be able to point at the file count it used.
"""

BOUNDARY_MIN = 1
BOUNDARY_MAX = 5

SOURCE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py",
               ".swift", ".m", ".mm"}


def _package_label(rel):
    return package_of(rel) or "<root>"


def clamp(value):
    return max(BOUNDARY_MIN, min(BOUNDARY_MAX, value))


def package_of(rel):
    """The file's package: its first two path segments, or the first when shallow.

    "src/api/routes.ts" -> "src/api". A file at the repo root has no package.
    Heuristic by necessity: this tool does not read workspace manifests, so it
    cannot tell "src/api" from a nested package inside it.
    """
    parts = rel.split("/")
    if len(parts) == 1:
        return ""
    if len(parts) == 2:
        return parts[0]
    return "/".join(parts[:2])


def crosses_boundary(rel, others):
    """True when any related file sits in a different top-level package."""
    base = package_of(rel)
    for other in others:
        if package_of(other) != base:
            return True
    return False


def _files_phrase(count):
    return "%d file%s" % (count, "" if count == 1 else "s")


def _calls_phrase(count):
    return "%d call site%s" % (count, "" if count == 1 else "s")


def defect_effort(rel, importers, no_test):
    """Rubric's reduced formula: a rule match is mechanical, local work."""
    boundary = crosses_boundary(rel, importers)
    effort = clamp(1 + (1 if no_test else 0) + (1 if boundary else 0))

    drivers = ["1 file", "%d importer%s" % (len(importers), "" if len(importers) == 1 else "s")]
    if boundary:
        drivers.append("crosses %s boundary"
                       % "→".join(sorted({_package_label(rel)} | {_package_label(i) for i in importers})))
    if no_test:
        drivers.append("no test runner")
    return effort, drivers


def call_profile(name, definition_rel, files):
    """Count files and call sites that mention `name`, excluding its definition.

    Word-boundary matching, not a call graph. Ordinal input, documented as such.
    Returns None for handlers with no usable symbol (e.g. "POST /webhooks/stripe").
    """
    import re

    symbol = name.rsplit(".", 1)[-1]
    if not symbol or not re.match(r"^[A-Za-z_$][\w$]*$", symbol):
        return None

    pattern = re.compile(r"\b%s\b" % re.escape(symbol))
    hits = []
    callsites = 0
    for f in files:
        if f.get("ext") not in SOURCE_EXTS:
            continue
        count = len(pattern.findall(f["text"]))
        if f["rel"] == definition_rel and count:
            count -= 1
        if count <= 0:
            continue
        hits.append(f["rel"])
        callsites += count
    return {"files": sorted(hits), "callsites": callsites}


def failure_mode_effort(rel, profile, no_test):
    """Rubric's five-term formula, measured instead of estimated by the model."""
    if profile is None:
        # An inline handler has no name to count: one file, one site, and say so.
        files = 1
        callsites = 1
        related = []
        unspecified = True
    else:
        files = 1 + len([f for f in profile["files"] if f != rel])
        callsites = max(1, profile["callsites"])
        related = profile["files"]
        unspecified = False

    boundary = crosses_boundary(rel, related)
    effort = clamp(1 + files // 3 + callsites // 5 + (1 if boundary else 0) + (1 if no_test else 0))

    drivers = [_files_phrase(files), _calls_phrase(callsites)]
    if unspecified:
        drivers.append("handler has no name to count")
    if boundary:
        drivers.append("crosses %s boundary"
                       % "→".join(sorted({_package_label(rel)} | {_package_label(r) for r in related})))
    if no_test:
        drivers.append("no test runner")
    return effort, drivers


def reverse_importers(files, entry_files=None):
    """file -> sorted list of files that import it."""
    from .imports import build_graph

    graph = build_graph(files)
    importers = {f["rel"]: [] for f in files}
    for source, targets in graph.items():
        for target in targets:
            importers.setdefault(target, []).append(source)
    return {rel: sorted(set(values)) for rel, values in importers.items()}


def site_index(files):
    """file -> sites, for attributing a finding to its enclosing function."""
    from .context import extract_sites

    sites, _ = extract_sites(files, lambda rel: 5, max_sites=10 ** 9, min_reach=0)
    index = {}
    for site in sites:
        index.setdefault(site["file"], []).append(site)
    return index


def site_at(index, rel, line):
    """Innermost site containing the line, or None for module-level code."""
    best = None
    for site in index.get(rel, []):
        start, end = site["lines"]
        if start <= line <= end:
            if best is None or (end - start) < (best["lines"][1] - best["lines"][0]):
                best = site
    return best


def apply_efforts(findings, files, no_test, trust_model=False, index=None):
    """Set effort and drivers on every finding. Single path for detect and rank."""
    importers = reverse_importers(files)
    sources = [f for f in files if f["ext"] in SOURCE_EXTS]
    needs_sites = any(f.get("class") == "failure-mode" for f in findings)
    if needs_sites and index is None:
        index = site_index(files)

    for finding in findings:
        if trust_model and finding.get("class") == "failure-mode" and finding.get("effort") is not None:
            continue
        if finding.get("class") == "defect":
            effort, drivers = defect_effort(
                finding["file"], importers.get(finding["file"], []), no_test)
        else:
            site = site_at(index or {}, finding["file"], finding.get("line", 0))
            profile = call_profile(site["function"], finding["file"], sources) if site else None
            effort, drivers = failure_mode_effort(finding["file"], profile, no_test)
        finding["effort"] = effort
        finding["effort_drivers"] = drivers
    return findings
