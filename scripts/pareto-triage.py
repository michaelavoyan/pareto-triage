#!/usr/bin/env python3
"""pareto-triage — defect ranking for a codebase.

Phases that are not implemented refuse to run and write nothing. An empty
artifact is never a substitute for a phase that did not happen.
"""

import hashlib
import json
import shlex
import sys
from pathlib import Path

from lib.walk import walk, count_loc, is_test_path
from lib.lang import (SUPPORTED_LABEL, frameworks, language_label, languages,
                      read_manifests, split_supported, test_runner)
from lib.entry import (extract_entrypoints, entrypoint_counts,
                       filter_entrypoints_by_language, ENTRY_LANGUAGE_FLOOR)
from lib.schema import apply_confidence_cap, validate_finding, parse_jsonl
from lib.rules import detect_defects, rule_coverage
from lib.imports import compute_reach, entry_paths, read_aliases, seeds_from_entrypoints
from lib.context import (extract_sites, load_sites, site_contains, MAX_SITES_DEFAULT,
                         MAX_SOURCE_LINES, SAMPLE_ORDERS, DEFAULT_SAMPLE_ORDER, DEFAULT_SEED)
from lib import sampling
from lib.effort import apply_efforts
from lib.score import (annotate, cluster_findings, shape, quadrant, coverage_curve,
                       curve_markers, pareto_point, pareto_ladder, DEFAULT_BUDGETS)
from lib.render import render
from lib.redact import redact_findings
from lib import calibrate, prompts, probes
from lib import verify

from lib.version import VERSION
MIN_LOC_DEFAULT = 10000


def parse_args(argv):
    positional = []
    flags = {}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if not arg.startswith("--"):
            positional.append(arg)
            index += 1
            continue
        if "=" in arg:
            key, value = arg[2:].split("=", 1)
            flags[key] = value
        elif index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            flags[arg[2:]] = argv[index + 1]
            index += 1
        else:
            flags[arg[2:]] = True
        index += 1
    return positional, flags


def num(value):
    return "{:,}".format(value)


def _paths(positional, flags):
    repo = Path(positional[0] if positional else ".").resolve()
    out = Path(flags["out"]).resolve() if "out" in flags else repo / "out"
    return repo, out


def _load_scope(out_dir):
    path = out_dir / "scope.json"
    if not path.exists():
        print("no scope.json in %s — run: pareto-triage gate <repo>" % out_dir, file=sys.stderr)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path):
    if not path.exists():
        return None
    records, bad = parse_jsonl(path.read_text(encoding="utf-8"))
    if bad:
        for line, error in bad:
            print("%s line %d: %s" % (path, line, error), file=sys.stderr)
        raise ValueError("malformed %s" % path.name)
    return [record for _, record in records]


def _judgment_ids(judgments, sites):
    """Site ids phase 2 judged, from out/judgments.jsonl.

    A judgment exists for every site phase 2 looked at, clean or not. Only ids
    that name a site in context.jsonl count, so sites_judged cannot exceed
    sites_total. Impossible ids and malformed records are returned for the
    caller to warn about, never silently folded into the count.
    """
    judged, unknown, skipped = set(), [], []
    for index, record in enumerate(judgments or [], start=1):
        if not isinstance(record, dict):
            skipped.append((index, "record is not an object"))
            continue
        site_id = record.get("site_id")
        findings = record.get("findings")
        if not isinstance(site_id, str) or not site_id.strip():
            skipped.append((index, "site_id must be a non-empty string"))
            continue
        if isinstance(findings, bool) or not isinstance(findings, int) or findings < 0:
            skipped.append((index, "findings must be a non-negative integer"))
            continue
        if site_id not in sites:
            unknown.append(site_id)
            continue
        judged.add(site_id)
    return judged, unknown, skipped


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _file_digest(path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs_digest(out_dir):
    return {
        "defects": _file_digest(out_dir / "defects.jsonl"),
        "failure_modes": _file_digest(out_dir / "failure-modes.jsonl"),
        "judgments": _file_digest(out_dir / "judgments.jsonl"),
    }


def _sources_digest(files):
    digest = hashlib.sha256()
    for f in sorted(files, key=lambda x: x["rel"]):
        digest.update(f["rel"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(f["text"].encode("utf-8")).digest())
    return digest.hexdigest()


CONFIDENCE_ORDER = {"low": 0, "med": 1, "high": 2}


def _max_depth(flags):
    """--max-depth, defaulting to the documented 3."""
    raw = flags.get("max-depth", 3)
    try:
        depth = int(raw)
    except (TypeError, ValueError):
        print("--max-depth must be an integer", file=sys.stderr)
        return None
    if depth < 1 or depth > 10:
        print("--max-depth must be between 1 and 10", file=sys.stderr)
        return None
    return depth


def _apply_cap(findings, scope):
    cap = scope["gate"].get("confidence_cap")
    reason = scope["gate"].get("confidence_cap_reason")
    return sum(1 for finding in findings if apply_confidence_cap(finding, cap, reason))


def _dedupe_findings(findings):
    """One finding per (file, line, taxonomy). Keep the more confident detector."""
    kept = {}
    dropped = []
    for finding in findings:
        key = (finding.get("file"), finding.get("line"), finding.get("taxonomy"))
        previous = kept.get(key)
        if previous is None:
            kept[key] = finding
            continue
        if CONFIDENCE_ORDER.get(finding.get("confidence"), 0) > CONFIDENCE_ORDER.get(previous.get("confidence"), 0):
            dropped.append(str(previous.get("id")))
            kept[key] = finding
        else:
            dropped.append(str(finding.get("id")))
    return list(kept.values()), dropped


def _print_swift_notes(reach_meta):
    """Say what the Swift graph actually knows, instead of leaving it implied."""
    swift = reach_meta.get("swift")
    if swift and swift.get("swift_files"):
        print("swift      %d file(s), %d mapped to a target, %d mention edge(s); "
              "module imports add no edge"
              % (swift["swift_files"], swift["mapped_files"], swift["mention_edges"]))
        if swift.get("note"):
            print("           %s" % swift["note"])
    objc = reach_meta.get("objc")
    if objc and objc.get("imports"):
        print("objc       %d #import(s), %d resolved, %d by unique basename, "
              "%d ambiguous (not resolved)"
              % (objc["imports"], objc["resolved"], objc["basename_fallbacks"],
                 objc["ambiguous"]))


def _stale_reasons(ranked, out_dir, files):
    """Why a ranked.json no longer describes the tree it sits next to."""
    if not ranked.get("sources_hash") and not ranked.get("inputs_hash"):
        return ["ranked.json carries no input hashes (produced before staleness tracking); re-run: pareto-triage rank"]

    reasons = []
    if _inputs_digest(out_dir) != ranked.get("inputs_hash"):
        reasons.append("findings changed after the ranking: defects.jsonl, failure-modes.jsonl, "
                       "or judgments.jsonl was rewritten")
    if _sources_digest(files) != ranked.get("sources_hash"):
        reasons.append("source files changed after the ranking")
    if ranked.get("tool_version") != VERSION:
        reasons.append("ranked by pareto-triage %s; this is %s"
                       % (ranked.get("tool_version"), VERSION))
    return reasons


def print_gate(scope):
    size = scope["size"]
    langs = ", ".join("%s %s" % (entry["lang"], num(entry["loc"])) for entry in size["by_language"][:6])
    print("pareto-triage %s — gate" % VERSION)
    print("repo       %s" % scope["root"])
    print("files      %s scanned, %s skipped" % (num(size["scanned_files"]), num(size["skipped_files"])))
    print("code       %s non-blank lines%s" % (num(size["loc"]), " (%s)" % langs if langs else ""))
    if size["unsupported"]:
        print("unsupported %s"
              % ", ".join("%s (%s file%s, %s lines)"
                          % (e["lang"], num(e["files"]), "" if e["files"] == 1 else "s",
                             num(e["loc"]))
                          for e in size["unsupported"]))
    tests = scope["tests"]
    print("tests      %s" % (tests["runner"] if tests["present"] else "none detected"))
    print("frameworks %s" % (", ".join(f["name"] for f in scope["frameworks"]) or "none detected"))
    counts = scope["entrypoint_kinds"]
    shown = ["http", "ui", "middleware", "background", "consumer", "cron", "cli",
             "app", "public-api"]
    print("entries    %s"
          % ", ".join("%d %s" % (counts.get(kind, 0), kind)
                      for kind in shown if counts.get(kind, 0)))
    for warning in scope["warnings"]:
        print("warning    %s" % warning)

    print("")
    if not scope["gate"]["ok"]:
        print("GATE: REFUSED")
        for reason in scope["gate"]["reasons"]:
            print("  - %s" % reason)
        print("")
        print("Refusing is the correct outcome. Do not improvise a report.")
        return
    print("GATE: PASS")
    if scope["gate"]["confidence_cap"]:
        print("confidence capped at %s (%s)"
              % (scope["gate"]["confidence_cap"], scope["gate"]["confidence_cap_reason"]))


def _ignored_languages(ignored):
    """`python (39 entrypoints, 0.3% of supported lines)` for warnings."""
    return ", ".join("%s (%s entrypoint%s, %.1f%% of supported lines)"
                     % (entry["lang"], num(entry["entrypoints"]),
                        "" if entry["entrypoints"] == 1 else "s", 100 * entry["share"])
                     for entry in ignored)


def _unruled_languages(coverage, supported):
    """Supported languages with scanned files but no detector.

    Unsupported languages are excluded: they already have a warning of their
    own. The question here is whether a language this tool claims to support
    was actually examined, not whether a language it does not support was.
    """
    return [row for row in coverage.get("by_language", [])
            if row["lang"] in supported and row["files_with_rules"] == 0]


def _unruled_sentence(row):
    return ("no rules were applied to %s file%s of %s"
            % (num(row["files"]), "" if row["files"] == 1 else "s",
               language_label(row["lang"])))


def _print_rule_coverage(coverage):
    """Say which languages a detector read, not only how many findings fell out."""
    rows = coverage.get("by_language") or []
    for index, row in enumerate(rows):
        prefix = "rules      " if index == 0 else "           "
        if row["files_with_rules"]:
            detail = "%d/%d files (%d rule%s)" % (
                row["files_with_rules"], row["files"], len(row["rules"]),
                "" if len(row["rules"]) == 1 else "s")
        else:
            detail = "%d/%d files (no rules)" % (row["files_with_rules"], row["files"])
        print("%s%-12s %s" % (prefix, row["lang"], detail))


def cmd_gate(positional, flags):
    repo, out_dir = _paths(positional, flags)
    raw_min = flags.get("min-loc", MIN_LOC_DEFAULT)
    try:
        min_loc = int(raw_min)
    except (TypeError, ValueError):
        print("--min-loc must be an integer", file=sys.stderr)
        return 2
    if min_loc < 0:
        print("--min-loc must be non-negative", file=sys.stderr)
        return 2

    walked = walk(repo)
    files = walked["files"]
    if not files:
        print("no readable files under %s" % walked["root"], file=sys.stderr)
        return 2

    by_lang = languages(files)
    supported, unsupported = split_supported(by_lang)
    supported_loc = sum(entry["loc"] for entry in supported)
    coverage = rule_coverage(files)
    unruled = _unruled_languages(coverage, {entry["lang"] for entry in supported})

    manifests = read_manifests(walked["root"])
    fw = frameworks(manifests)
    tests = test_runner(manifests, files)
    entrypoints = extract_entrypoints(files)
    entrypoints, ignored_languages = filter_entrypoints_by_language(entrypoints, supported)
    counts = entrypoint_counts(entrypoints)

    reasons = []
    if not supported:
        reasons.append("no source files in a language this tool supports "
                       "(%s)" % SUPPORTED_LABEL)
    elif supported_loc < min_loc:
        reasons.append(
            "only %s non-blank lines of supported code; minimum is %s — too few findings to rank honestly"
            % (num(supported_loc), num(min_loc)))
    if not entrypoints:
        if ignored_languages:
            reasons.append(
                "every detected entrypoint comes from a language below the 5%% floor: %s; "
                "reachability would be invented" % _ignored_languages(ignored_languages))
        else:
            reasons.append("no entrypoints detected (routes, CLI commands, cron jobs, consumers, "
                           "Android components, iOS app/UI classes); reachability would be invented")
    if walked["truncated"]:
        reasons.append("file cap reached — scan is incomplete")

    warnings = []
    if ignored_languages:
        warnings.append("entrypoints ignored from languages below the %.0f%% floor: %s"
                        % (100 * ENTRY_LANGUAGE_FLOOR, _ignored_languages(ignored_languages)))
    if not tests["present"]:
        warnings.append("no test runner detected: confidence capped at med, verification unavailable")
    if unsupported:
        warnings.append("%d unsupported language(s) present and ignored: %s"
                        % (len(unsupported), ", ".join(e["lang"] for e in unsupported)))
    for row in unruled:
        warnings.append("%s — these files are unassessed, not clean"
                        % _unruled_sentence(row))
    if walked["truncated"]:
        warnings.append("stopped after %s files" % num(len(files)))
    if walked["skipped"]:
        warnings.append("%s files skipped (binary, oversized, or non-utf-8)" % num(len(walked["skipped"])))

    scope = {
        "tool": "pareto-triage",
        "tool_version": VERSION,
        "root": walked["root"],
        "generated_at": _now(),
        "gate": {
            "ok": not reasons,
            "reasons": reasons,
            "min_loc": min_loc,
            "entrypoint_language_floor": ENTRY_LANGUAGE_FLOOR,
            "confidence_cap": None if tests["present"] else "med",
            "confidence_cap_reason": None if tests["present"] else "no test runner detected",
        },
        "size": {
            "scanned_files": len(files),
            "skipped_files": len(walked["skipped"]),
            "loc": supported_loc,
            "total_loc": sum(count_loc(f["text"]) for f in files),
            "by_language": supported,
            "unsupported": unsupported,
        },
        "languages": {
            "supported": [e["lang"] for e in supported],
            "unsupported": [e["lang"] for e in unsupported],
        },
        "rule_coverage": coverage,
        "frameworks": fw,
        "tests": tests,
        "entrypoint_kinds": counts,
        "entrypoints": entrypoints,
        "entrypoints_ignored": ignored_languages,
        "skipped": walked["skipped"][:200],
        "warnings": warnings,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "scope.json"
    target.write_text(json.dumps(scope, indent=2) + "\n", encoding="utf-8")

    print_gate(scope)
    print("")
    print("wrote %s" % target)
    return 0 if scope["gate"]["ok"] else 1


def cmd_context(positional, flags):
    repo, out_dir = _paths(positional, flags)
    scope = _load_scope(out_dir)
    if scope is None:
        return 2
    if not scope["gate"]["ok"]:
        print("gate was refused; refusing to build a candidate set", file=sys.stderr)
        return 1

    try:
        max_sites = int(flags.get("limit", MAX_SITES_DEFAULT))
        max_source = int(flags.get("max-lines", MAX_SOURCE_LINES))
    except (TypeError, ValueError):
        print("--limit and --max-lines must be integers", file=sys.stderr)
        return 2
    if max_sites < 1 or max_source < 5:
        print("--limit must be >= 1 and --max-lines >= 5", file=sys.stderr)
        return 2

    order = str(flags.get("sample-order", DEFAULT_SAMPLE_ORDER))
    if order not in SAMPLE_ORDERS:
        print("--sample-order must be one of: %s" % ", ".join(SAMPLE_ORDERS), file=sys.stderr)
        return 2
    try:
        seed = int(flags.get("seed", DEFAULT_SEED))
    except (TypeError, ValueError):
        print("--seed must be an integer", file=sys.stderr)
        return 2

    save_candidates = flags.get("save-candidates")
    write_population = bool(flags.get("all")) or save_candidates is not None
    candidates_path = None
    if write_population:
        if save_candidates in (None, True):
            candidates_path = out_dir / "candidates.jsonl"
        else:
            candidates_path = Path(str(save_candidates)).expanduser().resolve()

    depth = _max_depth(flags)
    if depth is None:
        return 2

    walked = walk(repo)
    files = walked["files"]
    aliases = read_aliases(repo)
    entrypoints = scope.get("entrypoints") or []
    if not entrypoints:
        print("scope.json has no entrypoints; nothing is reachable", file=sys.stderr)
        return 1

    entry_files = {e["file"] for e in entrypoints}
    seeds = seeds_from_entrypoints(entrypoints)
    reach, reach_meta = compute_reach(files, entry_files, max_depth=depth,
                                      seeds=seeds, aliases=aliases)
    paths = entry_paths(files, entry_files, max_depth=depth, aliases=aliases,
                        seeds=seeds)

    first_entry = {}
    entries_by_file = {}
    for entry in sorted(entrypoints, key=lambda e: (e["file"], e["line"], e["detail"])):
        first_entry.setdefault(entry["file"], entry)
        entries_by_file.setdefault(entry["file"], []).append(entry)

    def _entry_for(site, path):
        candidates = entries_by_file.get(path[0]) or []
        if not candidates:
            return None
        for entry in candidates:
            if entry["detail"] == site["function"]:
                return entry
        before = [e for e in candidates if e["line"] <= site["lines"][0]]
        return before[-1] if before else candidates[0]

    sites, summary = extract_sites(files, reach, max_sites=max_sites, max_source_lines=max_source,
                                   include_enclosing=bool(flags.get("include-enclosing")),
                                   all_sites=write_population, order=order, seed=seed)

    for site in sites:
        path = paths.get(site["file"]) or [site["file"]]
        entry = _entry_for(site, path)
        call_path = ([entry["detail"]] if entry else []) + path[1:] + [site["function"]]
        deduped = []
        for step in call_path:
            if not deduped or deduped[-1] != step:
                deduped.append(step)
        site["call_path"] = deduped

    def _record(site):
        return {
            "site_id": site["site_id"],
            "file": site["file"],
            "function": site["function"],
            "lines": site["lines"],
            "lang": site["lang"],
            "reach": site["reach"],
            "call_path": site["call_path"],
            "source": site["source"],
            "surrounding": site["surrounding"],
            "truncated": site["truncated"],
            **({"enclosed_by": site["enclosed_by"]} if site.get("enclosed_by") else {}),
        }

    records = [_record(site) for site in sites]

    if not records:
        print("no candidate sites: no functions found in files with reach >= 2", file=sys.stderr)
        print("this phase refuses rather than write an empty context.jsonl. "
              "Check that entrypoints point at source that contains functions.", file=sys.stderr)
        return 1

    selected_count = summary["emitted"]
    context_records = records[:selected_count]

    def _write_jsonl(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                        encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "context.jsonl"
    _write_jsonl(target, context_records)
    if candidates_path is not None:
        _write_jsonl(candidates_path, records)

    sample_payload = {
        "mode": order,
        "seed": seed,
        "population": summary["population"],
        "kept": summary["emitted"],
        "per_file": summary["per_file"],
        "judgeable": {
            "candidates": summary["judgeable_candidates"],
            "filtered": summary["judgeable_filtered"],
            "fallback": summary["judgeable_fallback"],
        },
    }
    sample_path = out_dir / "sample.json"
    sample_path.write_text(json.dumps(sample_payload, indent=2) + "\n", encoding="utf-8")

    by_reach = {}
    for site in context_records:
        by_reach[site["reach"]] = by_reach.get(site["reach"], 0) + 1
    reachable_files = len({s["file"] for s in context_records})

    print("pareto-triage %s — context" % VERSION)
    print("files      %s scanned, %s with reach >= 2, %s ignored as unreachable"
          % (num(len(files)), num(reachable_files), num(summary["unreachable_source_files"])))
    print("sites      %s of %s candidates%s; %s trivial accessor(s) skipped"
          % (num(summary["emitted"]), num(summary["candidates"]),
             " (limit %s hit)" % num(summary["limit"]) if summary["limit_hit"] else "",
             num(summary["trivial_excluded"])))
    if candidates_path is not None:
        print("population %s candidate sites written; first %s match context.jsonl"
              % (num(summary["population"]), num(summary["emitted"])))
    print("reach      %s"
          % ", ".join("reach %d: %s" % (level, num(by_reach[level]))
                      for level in sorted(by_reach, reverse=True)))
    print("mode       %s (depth %d)" % (reach_meta["mode"], reach_meta["max_depth"]))
    _print_swift_notes(reach_meta)
    for error in summary["parse_errors"][:10]:
        print("warning    %s: cannot parse (%s)" % (error["file"], error["reason"]))
    if len(summary["parse_errors"]) > 10:
        print("warning    … %d more unparseable files" % (len(summary["parse_errors"]) - 10))
    print("sample     %s, seed %d: kept %s of %s candidates, max %d per file"
          % (order, seed, num(summary["emitted"]), num(summary["population"]),
             summary["per_file"]))
    print("judgeable  %s of %s candidates (%d%%) have a failure surface and 4+ non-blank lines; "
          "%s filtered from the sample"
          % (num(summary["judgeable_candidates"]), num(summary["candidates"]),
             100 * summary["judgeable_candidates"] // max(summary["candidates"], 1),
             num(summary["judgeable_filtered"])))
    if summary["judgeable_fallback"]:
        if summary["judgeable_candidates"] < summary["limit"]:
            print("warning    only %s judgeable site(s) for a limit of %s: kept %s "
                  "non-judgeable site(s) from the ranked fallback"
                  % (num(summary["judgeable_candidates"]), num(summary["limit"]),
                     num(summary["judgeable_fallback"])))
        else:
            print("fallback   per-file caps left the sample short: kept %s non-judgeable "
                  "site(s) in ranked order" % num(summary["judgeable_fallback"]))
    print("           rule findings cover every scanned file; this is a sample only for judgment")
    if order == "ranked":
        print("selection  reach → inbound edges → body size, max %d per file"
              % summary["per_file"])
    if summary["limit_hit"]:
        print("warning    site cap reached; %s candidates were not included"
              % num(summary["candidates"] - summary["emitted"]))
    print("")
    print("wrote %s" % target)
    if candidates_path is not None:
        print("wrote %s" % candidates_path)
    print("wrote %s" % sample_path)
    return 0


def cmd_sampling(positional, flags):
    repo, out_dir = _paths(positional, flags)
    candidates_path = out_dir / "candidates.jsonl"

    try:
        population = _load_jsonl(candidates_path)
        defects = _load_jsonl(out_dir / "defects.jsonl")
        failure_modes = _load_jsonl(out_dir / "failure-modes.jsonl")
    except ValueError:
        return 2

    if population is None:
        print("no candidates.jsonl in %s — run: pareto-triage context <repo> --all" % out_dir,
              file=sys.stderr)
        return 2
    if not population:
        print("candidates.jsonl is empty; there is no population to sample", file=sys.stderr)
        return 2
    if defects is None:
        print("no defects.jsonl in %s — run: pareto-triage detect <repo>" % out_dir,
              file=sys.stderr)
        return 2

    sample_meta = None
    sample_path = out_dir / "sample.json"
    if sample_path.exists():
        try:
            sample_meta = json.loads(sample_path.read_text(encoding="utf-8"))
        except ValueError:
            print("warning    sample.json is not valid JSON; ignoring it", file=sys.stderr)
    if sample_meta and sample_meta.get("mode") == "random":
        print("warning    candidates.jsonl starts with a random sample (seed %s), not the "
              "ranked set: this compares random against random." % sample_meta.get("seed", 0),
              file=sys.stderr)
        print("warning    for the ordering comparison re-run: pareto-triage context <repo> "
              "--all --sample-order ranked", file=sys.stderr)

    try:
        limit = int(flags.get("limit", MAX_SITES_DEFAULT))
        seed = int(flags.get("seed", sampling.DEFAULT_SEED))
    except (TypeError, ValueError):
        print("--limit and --seed must be integers", file=sys.stderr)
        return 2
    if limit < 1:
        print("--limit must be >= 1", file=sys.stderr)
        return 2

    result = sampling.measure(population, defects, limit=limit, seed=seed)
    result.update({
        "tool": "pareto-triage",
        "tool_version": VERSION,
        "repo": str(repo),
        "generated_at": _now(),
        "inputs": {
            "candidates": len(population),
            "defects": len(defects),
            "failure_modes_ignored": len(failure_modes or []),
        },
    })

    target = out_dir / "sampling.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    def _percent(block):
        return "%5.1f%% vs %5.1f%% (ratio %s, 95%% CI %+.3f..%+.3f)" % (
            100 * block["selected"], 100 * block["random"],
            "n/a" if block["ratio"] is None else "%.2f" % block["ratio"],
            block["ci95"][0], block["ci95"][1])

    print("pareto-triage %s — sampling" % VERSION)
    print("population %s candidates, %s selected, %s random (seed %d)"
          % (num(result["population"]), num(result["n"]), num(result["n"]), result["seed"]))
    print("file       %s" % _percent(result["file_density"]))
    print("line       %s" % _percent(result["line_density"]))
    print("verdict    %s" % result["verdict"])
    print("measure    rule findings only; phase-2 failure modes are not counted")
    print("")
    print("wrote %s" % target)
    return 0


def cmd_detect(positional, flags):
    repo, out_dir = _paths(positional, flags)
    scope = _load_scope(out_dir)
    if scope is None:
        return 2
    if not scope["gate"]["ok"]:
        print("gate was refused; refusing to scan", file=sys.stderr)
        return 1

    depth = _max_depth(flags)
    if depth is None:
        return 2

    walked = walk(repo)
    aliases = read_aliases(repo)
    scanned = [f for f in walked["files"] if not is_test_path(f["rel"])]
    test_files = len(walked["files"]) - len(scanned)
    coverage = rule_coverage(scanned)
    unruled = _unruled_languages(coverage, set(scope["languages"]["supported"]))
    findings, warnings = detect_defects(scanned)

    entry_files = {e["file"] for e in scope["entrypoints"]}
    seeds = seeds_from_entrypoints(scope["entrypoints"])
    reach, reach_meta = compute_reach(walked["files"], entry_files, max_depth=depth,
                                      seeds=seeds, aliases=aliases)

    no_test = not scope["tests"]["present"]
    for finding in findings:
        finding["reach"] = reach(finding["file"])
    apply_efforts(findings, walked["files"], no_test)
    capped = _apply_cap(findings, scope)

    sources = {f["rel"]: f["text"] for f in walked["files"]}
    invalid = []
    for finding in findings:
        errors = validate_finding(finding, sources=sources)
        if errors:
            invalid.append((finding["id"], errors))
    if invalid:
        for finding_id, errors in invalid:
            print("internal rule produced an invalid finding %s: %s" % (finding_id, "; ".join(errors)),
                  file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "defects.jsonl"
    target.write_text("".join(json.dumps(f, sort_keys=True) + "\n" for f in findings), encoding="utf-8")

    by_taxonomy = {}
    for finding in findings:
        by_taxonomy[finding["taxonomy"]] = by_taxonomy.get(finding["taxonomy"], 0) + 1
    unreachable = sum(1 for f in findings if f["reach"] <= 1)
    by_reach = {}
    for finding in findings:
        by_reach[finding["reach"]] = by_reach.get(finding["reach"], 0) + 1

    print("pareto-triage %s — detect" % VERSION)
    print("files      %s scanned, %s skipped as test code"
          % (num(len(scanned)), num(test_files)))
    _print_rule_coverage(coverage)
    print("findings   %d" % len(findings))
    for taxonomy, count in sorted(by_taxonomy.items(), key=lambda kv: -kv[1]):
        print("  %-28s %d" % (taxonomy, count))
    if capped:
        print("confidence %d finding(s) capped at %s (%s)"
              % (capped, scope["gate"]["confidence_cap"], scope["gate"]["confidence_cap_reason"]))
    if findings:
        print("reach      %s"
              % ", ".join("reach %d: %d" % (level, by_reach[level]) for level in sorted(by_reach, reverse=True)))
    print("mode       %s (depth %d, %d resolved edges)"
          % (reach_meta["mode"], reach_meta["max_depth"], reach_meta["resolved_edges"]))
    _print_swift_notes(reach_meta)
    for warning in warnings:
        print("warning    %s: %s" % (warning["path"], warning["reason"]))
    for row in unruled:
        print("warning    %s — these files are unassessed, not clean"
              % _unruled_sentence(row))
    print("")
    print("wrote %s" % target)
    return 0


def cmd_rank(positional, flags):
    repo, out_dir = _paths(positional, flags)
    scope = _load_scope(out_dir)
    if scope is None:
        return 2
    if not scope["gate"]["ok"]:
        print("gate was refused; nothing to rank", file=sys.stderr)
        return 1

    try:
        defects = _load_jsonl(out_dir / "defects.jsonl")
        failure_modes = _load_jsonl(out_dir / "failure-modes.jsonl")
        judgments = _load_jsonl(out_dir / "judgments.jsonl")
    except ValueError:
        return 2

    if defects is None and failure_modes is None:
        print("no findings to rank — run: pareto-triage detect <repo>", file=sys.stderr)
        return 2

    findings = list(defects or []) + list(failure_modes or [])

    sites = load_sites(out_dir / "context.jsonl")
    coverage = {"sites_total": len(sites) if sites is not None else None,
                "sites_judged": None, "sites_unjudged": None, "sites_unknown": []}
    if sites is not None:
        judged = set()
        for finding in failure_modes or []:
            site_id = finding.get("site_id")
            if not site_id:
                continue
            if site_id in sites:
                judged.add(site_id)
                site = sites[site_id]
                if finding.get("file") != site.get("file") or not site_contains(site, finding.get("line") or 0):
                    print("failure-mode %s cites %s:%s but site %s is %s:%s"
                          % (finding.get("id"), finding.get("file"), finding.get("line"),
                             site_id, site.get("file"), site.get("lines")),
                          file=sys.stderr)
                    return 1
            else:
                coverage["sites_unknown"].append(site_id)
        if coverage["sites_unknown"]:
            print("failure-mode records cite sites that are not in context.jsonl: %s"
                  % ", ".join(sorted(set(coverage["sites_unknown"]))[:10]), file=sys.stderr)
            return 1

        judged_clean, judgment_unknown, judgment_skipped = _judgment_ids(judgments, sites)
        if judgments is None:
            print("warning    judgments.jsonl is missing: sites judged clean in phase 2 are not "
                  "recorded, so coverage counts only sites with a finding", file=sys.stderr)
        for index, reason in judgment_skipped:
            print("warning    judgments.jsonl record %d skipped: %s" % (index, reason),
                  file=sys.stderr)
        if judgment_unknown:
            print("warning    judgments.jsonl cites sites that are not in context.jsonl and were "
                  "ignored: %s" % ", ".join(sorted(set(judgment_unknown))[:10]), file=sys.stderr)
        judged.update(judged_clean)
        coverage["sites_judged"] = min(len(judged), len(sites))
        coverage["sites_unjudged"] = len(sites) - coverage["sites_judged"]

        required = flags.get("require-coverage")
        if required not in (None, True):
            try:
                threshold = float(required)
            except (TypeError, ValueError):
                print("--require-coverage must be a number between 0 and 1", file=sys.stderr)
                return 2
            if sites and (len(judged) / len(sites)) < threshold:
                print("phase 2 covered %d of %d sites (%.0f%%), below --require-coverage %.0f%%"
                      % (len(judged), len(sites), 100 * len(judged) / len(sites), 100 * threshold),
                      file=sys.stderr)
                return 1
    elif judgments is not None:
        print("warning    judgments.jsonl is present but context.jsonl is missing; "
              "judgments cannot be attributed to sites and are ignored", file=sys.stderr)

    trust_model = bool(flags.get("trust-model-effort"))
    supplied = [f.get("id", "?") for f in findings
                if f.get("class") == "failure-mode" and f.get("effort") is not None]
    if supplied and not trust_model:
        print("failure-mode effort is derived from the rubric, not supplied by the model", file=sys.stderr)
        print("remove `effort` from: %s" % ", ".join(supplied[:10]), file=sys.stderr)
        print("see references/rubric.md; use --trust-model-effort to keep the supplied bands.", file=sys.stderr)
        return 1

    walked = walk(repo)
    no_test = not scope["tests"]["present"]
    sources = {f["rel"]: f["text"] for f in walked["files"]}
    strict = bool(flags.get("strict"))
    current_prompt = prompts.identity()

    scored = []
    unproven = []
    for finding in findings:
        errors = validate_finding(finding, sources=sources)
        is_failure_mode = finding.get("class") == "failure-mode"

        if not errors and is_failure_mode and sites is not None:
            site = sites.get(finding.get("site_id"))
            if finding.get("site_id") is None:
                errors.append("site_id is required when context.jsonl is present")
            elif site is None:
                errors.append("site_id %s is not in context.jsonl" % finding.get("site_id"))
            elif (finding.get("file") != site.get("file")
                  or not site_contains(site, finding.get("line") or 0)):
                errors.append("cites %s:%s but site %s is %s:%s"
                              % (finding.get("file"), finding.get("line"),
                                 finding.get("site_id"), site.get("file"), site.get("lines")))

        if not errors and is_failure_mode:
            stamp = (finding.get("prompt") or {}).get("hash")
            if stamp and stamp != current_prompt["hash"]:
                errors.append("produced under prompt %s, not %s; findings from different prompts "
                              "are not comparable" % (stamp, current_prompt["hash"]))

        if not errors:
            scored.append(finding)
            continue

        if not is_failure_mode or strict:
            print("merge gate rejected %s; nothing written" % finding.get("id", "?"), file=sys.stderr)
            for error in errors:
                print("  %s" % error, file=sys.stderr)
            if not is_failure_mode:
                print("a tool detector produced an invalid finding: that is a bug in this repo, "
                      "not in the input", file=sys.stderr)
            return 1

        unproven.append({
            "id": finding.get("id"),
            "class": finding.get("class"),
            "taxonomy": finding.get("taxonomy"),
            "file": finding.get("file"),
            "line": finding.get("line"),
            "reason": "; ".join(errors),
        })

    if unproven:
        print("unproven   %d failure mode(s) could not be scored; listed in the report, not ranked"
              % len(unproven), file=sys.stderr)

    findings = scored
    apply_efforts(findings, walked["files"], no_test, trust_model=trust_model)
    capped = _apply_cap(findings, scope)

    unreachable = [f for f in findings if f.get("reach") == 0]
    if unreachable:
        print("dropped    %d finding(s) with no path from any entrypoint" % len(unreachable),
              file=sys.stderr)
        findings = [f for f in findings if f.get("reach") != 0]

    findings, duplicates = _dedupe_findings(findings)

    budgets = DEFAULT_BUDGETS
    if flags.get("budget") not in (None, True):
        raw = str(flags["budget"]).split(",")
        if len(raw) != 3:
            print("--budget takes three comma-separated effort units, e.g. 5,15,30", file=sys.stderr)
            return 2
        try:
            budgets = tuple(float(part) for part in raw)
        except ValueError:
            print("--budget values must be numbers", file=sys.stderr)
            return 2

    annotate(findings)
    clusters = cluster_findings(findings)
    shape_info = shape(clusters)
    quad = quadrant(findings)
    curve = coverage_curve(clusters)
    markers = curve_markers(clusters, budgets)
    pareto = pareto_point(clusters)
    ladder = pareto_ladder(clusters)
    if shape_info["verdict"] == "insufficient":
        # The arithmetic can still produce a cheap-looking prefix at two
        # clusters. Nothing about that prefix is evidence, so the ladder and
        # the headline are not allowed to say "shortcut".
        for row in ladder:
            row["shortcut"] = False
        pareto = dict(pareto, shortcut=False, insufficient=True)

    input_hash = hashlib.sha256(
        "\n".join(json.dumps(f, sort_keys=True) for f in sorted(findings, key=lambda x: x["id"])).encode("utf-8")
    ).hexdigest()

    blocking = [c for c in clusters if c["taxonomy"] in
                ("missing-authz", "sql-injection", "command-injection", "code-injection",
                 "unsafe-deserialization", "hardcoded-secret", "tls-verification-disabled")]

    rule_rows = (scope.get("rule_coverage") or rule_coverage(walked["files"]))["by_language"]
    supported_langs = set(scope["languages"]["supported"])

    could_not_determine = []
    if failure_modes is None:
        could_not_determine.append(
            "failure-mode tier not run: this report covers tool-verifiable defects only. "
            "Timeouts, idempotency, swallowed errors, and boundedness were not assessed.")
    if sites is not None and judgments is None:
        could_not_determine.append(
            "phase 2 wrote no judgments.jsonl: a judged-and-clean site is indistinguishable "
            "from an unjudged one, so coverage counts only sites with a recorded finding.")
    could_not_determine.append(
        "reachability is file-level (depth 3). Dynamic dispatch, dependency injection, "
        "event buses, and monorepo path aliases are invisible.")
    if scope["languages"]["unsupported"]:
        ignored = []
        for entry in scope["size"]["unsupported"]:
            if entry.get("files") is not None:
                ignored.append("%s (%s file%s)"
                               % (entry["lang"], num(entry["files"]),
                                  "" if entry["files"] == 1 else "s"))
            else:
                ignored.append(entry["lang"])
        could_not_determine.append(
            "ignored languages: %s. Findings there are not counted, which lowers impact."
            % ", ".join(ignored))
    for row in rule_rows:
        if row["lang"] not in supported_langs:
            continue
        label = language_label(row["lang"])
        if row["files_with_rules"] == 0:
            could_not_determine.append(
                "%s: the tool has no %s defect rules, so this report says nothing about "
                "defects in them." % (_unruled_sentence(row), label))
        elif row["files_with_rules"] < row["files"]:
            could_not_determine.append(
                "rules cover %d of %d files of %s: the remaining %d have no detector and "
                "are unassessed, not clean."
                % (row["files_with_rules"], row["files"], label,
                   row["files"] - row["files_with_rules"]))
    if not scope["tests"]["present"]:
        could_not_determine.append(
            "no test runner detected: no fix can be verified, and effort bands assume no test work exists.")
    if scope["size"]["skipped_files"]:
        could_not_determine.append(
            "%s files were skipped (binary, oversized, or non-utf-8)." % num(scope["size"]["skipped_files"]))
    if blocking:
        could_not_determine.append(
            "%d finding(s) are security-relevant and should not wait for batch scheduling." % len(blocking))

    ranked = {
        "tool": "pareto-triage",
        "tool_version": VERSION,
        "repo_name": Path(scope["root"]).name,
        "prompt": prompts.identity(),
        "confidence_cap": scope["gate"].get("confidence_cap"),
        "confidence_cap_reason": scope["gate"].get("confidence_cap_reason"),
        "generated_at": _now(),
        "input_hash": input_hash,
        "inputs_hash": _inputs_digest(out_dir),
        "sources_hash": _sources_digest(walked["files"]),
        "coverage": {
            "defects": len(defects or []),
            "failure_modes": len(failure_modes or []),
            "sites_total": coverage["sites_total"],
            "sites_judged": coverage["sites_judged"],
            "sites_unjudged": coverage["sites_unjudged"],
        },
        "rule_coverage": {"by_language": rule_rows},
        "shape": shape_info,
        "quadrant": quad,
        "curve": curve,
        "curve_markers": markers,
        "pareto": pareto,
        "pareto_ladder": ladder,
        "clusters": clusters,
        "findings": sorted(findings, key=lambda x: (-x["priority"], x["file"], x["line"])),
        "blocking_security": [c["key"] for c in blocking],
        "unproven": unproven,
        "could_not_determine": could_not_determine,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "ranked.json"
    target.write_text(json.dumps(ranked, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print("pareto-triage %s — rank" % VERSION)
    print("findings   %d defects, %d failure modes"
          % (len(defects or []), len(failure_modes or [])))
    if coverage["sites_total"] is not None:
        print("coverage   %d of %d sites judged by phase 2"
              % (coverage["sites_judged"], coverage["sites_total"]))
    if capped:
        print("confidence %d finding(s) capped at %s" % (capped, scope["gate"]["confidence_cap"]))
    if duplicates:
        print("dedupe     %d duplicate(s) dropped: %s"
              % (len(duplicates), ", ".join(duplicates[:5]) + ("…" if len(duplicates) > 5 else "")))
    print("clusters   %d" % len(clusters))
    if shape_info["verdict"] == "insufficient":
        print("shape      insufficient — C20 %.0f%% over %d cluster%s; a shape verdict needs at least %d"
              % (100 * shape_info["c20"], shape_info["n_clusters"],
                 "" if shape_info["n_clusters"] == 1 else "s", shape_info["min_clusters"]))
    else:
        print("shape      %s — C20 %.0f%% (top %d of %d carry that share of impact)"
              % (shape_info["verdict"], 100 * shape_info["c20"], shape_info["top_n"],
                 shape_info["n_clusters"]))
    counts = quad["counts"]
    print("quadrant   %d do now, %d schedule, %d anytime, %d ignore"
          % (counts["quick_wins"], counts["batch_2"], counts["free"], counts["skip"]))
    if blocking:
        print("security   %d finding(s) flagged outside normal batches" % len(blocking))
    print("")
    print("wrote %s" % target)
    return 0


def cmd_report(positional, flags):
    repo, out_dir = _paths(positional, flags)
    ranked_path = out_dir / "ranked.json"
    if not ranked_path.exists():
        print("no ranked.json in %s — run: pareto-triage rank <repo>" % out_dir, file=sys.stderr)
        return 2
    scope = _load_scope(out_dir)
    if scope is None:
        return 2

    ranked = json.loads(ranked_path.read_text(encoding="utf-8"))

    stale = _stale_reasons(ranked, out_dir, walk(repo)["files"])
    if stale and not flags.get("allow-stale"):
        print("refusing to report: ranked.json is stale", file=sys.stderr)
        for reason in stale:
            print("  - %s" % reason, file=sys.stderr)
        print("re-run the pipeline, or pass --allow-stale to publish with a stale banner.", file=sys.stderr)
        return 1
    if stale:
        ranked["stale"] = {"reasons": stale, "ranked_at": ranked.get("generated_at")}
        print("warning    publishing a stale ranking (--allow-stale)", file=sys.stderr)
        for reason in stale:
            print("warning    - %s" % reason, file=sys.stderr)

    verification = None
    verify_path = out_dir / "verify.json"
    if verify_path.exists():
        try:
            verification = json.loads(verify_path.read_text(encoding="utf-8"))
        except ValueError:
            print("warning    verify.json is not valid JSON; ignoring it", file=sys.stderr)
            verification = None
        if verification is not None and verification.get("input_hash") != ranked.get("input_hash"):
            print("warning    verify.json was produced for a different ranking; ignoring it", file=sys.stderr)
            verification = None
    ranked["verification"] = verification

    calibration_path = out_dir / "calibration.json"
    if calibration_path.exists():
        try:
            ranked["calibration"] = json.loads(calibration_path.read_text(encoding="utf-8"))
        except ValueError:
            print("warning    calibration.json is not valid JSON; ignoring it", file=sys.stderr)

    sample_path = out_dir / "sample.json"
    if sample_path.exists():
        try:
            ranked["sample"] = json.loads(sample_path.read_text(encoding="utf-8"))
        except ValueError:
            print("warning    sample.json is not valid JSON; ignoring it", file=sys.stderr)

    published = json.loads(json.dumps(ranked))
    redactions = redact_findings(published["findings"])
    published["redactions"] = redactions

    html = render(published, scope)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "report.html"
    json_path = out_dir / "report.json"
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps(published, indent=2) + "\n", encoding="utf-8")

    print("pareto-triage %s — report" % VERSION)
    if flags.get("open"):
        import webbrowser
        opened = webbrowser.open(html_path.resolve().as_uri())
        print("board      %s" % ("opened in your browser" if opened else "could not open a browser; open %s" % html_path))

    print("verdict    %s" % ranked["shape"]["verdict"])
    if redactions:
        print("redacted   %d secret(s) across %d finding(s); defects.jsonl keeps the raw quote"
              % (sum(r["count"] for r in redactions),
                 len({(r["file"], r["line"]) for r in redactions})))
    print("wrote      %s" % html_path)
    print("wrote      %s" % json_path)
    return 0


def _scaffold_probes(ranked, out_dir, limit):
    """Write a template probe per top cluster. Never overwrites an existing file."""
    probes_dir = out_dir / "probes"
    probes_dir.mkdir(parents=True, exist_ok=True)

    written = []
    skipped = []
    findings = {f["id"]: f for f in ranked.get("findings", [])}
    for cluster in ranked.get("clusters", [])[:limit]:
        if cluster.get("class") == "defect":
            skipped.append((cluster.get("key"),
                            "tool-proven defect: the rule already quotes the line, no probe needed"))
            continue
        sample = findings.get(cluster.get("findings", [None])[0], {})
        site = {"lang": "py" if str(sample.get("file", "")).endswith(".py") else "ts"}
        body, ext = probes.render(cluster.get("taxonomy"), cluster, site)
        if body is None:
            skipped.append((cluster.get("key"), "no template for taxonomy %s" % cluster.get("taxonomy")))
            continue
        target = probes_dir / (verify.probe_slug(cluster.get("key")) + ext)
        if target.exists():
            skipped.append((cluster.get("key"), "%s already exists" % target.name))
            continue
        target.write_text(body, encoding="utf-8")
        written.append(target)
    return written, skipped


def _install_command(worktree):
    """Best-effort dependency install. Never run unless --install was passed."""
    for name, command in (
        ("package-lock.json", ["npm", "ci"]),
        ("pnpm-lock.yaml", ["pnpm", "install", "--frozen-lockfile"]),
        ("yarn.lock", ["yarn", "install", "--frozen-lockfile"]),
        ("requirements.txt", ["python3", "-m", "pip", "install", "-r", "requirements.txt"]),
    ):
        if (worktree / name).exists():
            return command
    return ["npm", "install"]


def cmd_verify(positional, flags):
    repo, out_dir = _paths(positional, flags)
    scope = _load_scope(out_dir)
    if scope is None:
        return 2
    if not scope["gate"]["ok"]:
        print("gate was refused; nothing to verify", file=sys.stderr)
        return 1

    ranked_path = out_dir / "ranked.json"
    if not ranked_path.exists():
        print("no ranked.json in %s — run: pareto-triage rank <repo>" % out_dir, file=sys.stderr)
        return 2
    ranked = json.loads(ranked_path.read_text(encoding="utf-8"))

    stale = _stale_reasons(ranked, out_dir, walk(repo)["files"])
    if stale:
        print("refusing to verify a stale ranking", file=sys.stderr)
        for reason in stale:
            print("  - %s" % reason, file=sys.stderr)
        return 1

    try:
        limit = int(flags.get("limit", 3))
        timeout = int(flags.get("probe-timeout", flags.get("timeout", verify.PROBE_TIMEOUT_DEFAULT)))
        suite_timeout = int(flags.get("suite-timeout", verify.SUITE_TIMEOUT_DEFAULT))
    except (TypeError, ValueError):
        print("--limit, --probe-timeout and --suite-timeout must be integers", file=sys.stderr)
        return 2

    if flags.get("scaffold"):
        written, skipped = _scaffold_probes(ranked, out_dir, limit)
        for path in written:
            print("scaffold   %s" % path)
        for cluster, why in skipped:
            print("skipped    %s: %s" % (cluster, why))
        if not written:
            print("no scaffolds written", file=sys.stderr)
            return 1 if skipped else 0

    worktree, info = verify.make_worktree(repo)
    if worktree is None:
        print("cannot verify: %s" % info["reason"], file=sys.stderr)
        return 2

    suite = {"status": "not-run",
             "reason": "no suite command: pass --suite '<command>' to run the project's tests"}
    try:
        if "suite" in flags and flags["suite"] is not True:
            argv = shlex.split(str(flags["suite"]))
            install_failed = False
            if flags.get("install"):
                install = verify.run_command(_install_command(worktree), worktree, suite_timeout)
                if install["exit"] != 0:
                    suite = {"status": "failed-to-install", "command": " ".join(argv),
                             "exit": install["exit"], "duration": install["duration"],
                             "output_tail": install["output_tail"]}
                    install_failed = True
            if not install_failed:
                result = verify.run_command(argv, worktree, suite_timeout)
                suite = {
                    "status": "ok" if result["exit"] == 0 else "failed",
                    "command": " ".join(argv),
                    "exit": result["exit"],
                    "duration": result["duration"],
                    "output_tail": result["output_tail"],
                }

        records = verify.verify_clusters(repo, ranked, out_dir / "probes", worktree,
                                         limit=limit, timeout=timeout)
        fix = None
        if flags.get("fix") not in (None, True):
            fix = verify.apply_patch(worktree, flags["fix"])
            if fix["applied"]:
                after = verify.verify_clusters(repo, ranked, out_dir / "probes", worktree,
                                               limit=limit, timeout=timeout)
                after_by_cluster = {r["cluster"]: r for r in after}
                merged = []
                for record in records:
                    second = after_by_cluster.get(record["cluster"])
                    if second is None or record.get("probe") is None or second.get("probe") is None:
                        merged.append(record)
                        continue
                    status, reason = verify.compare(record, second)
                    record = dict(record)
                    record["status"] = status
                    record["reason"] = reason
                    record["before"] = {"exit": record.get("exit"),
                                        "duration": record.get("duration")}
                    record["after"] = {"exit": second.get("exit"),
                                       "duration": second.get("duration")}
                    record["exit"] = second.get("exit")
                    merged.append(record)
                records = merged
            else:
                print("cannot apply the patch: %s" % fix["reason"], file=sys.stderr)
                return 2
    finally:
        if flags.get("keep-worktree"):
            print("worktree    kept at %s" % worktree, file=sys.stderr)
        else:
            verify.remove_worktree(repo, worktree, info)

    counts = verify.summarize(records)
    payload = {
        "tool": "pareto-triage",
        "tool_version": VERSION,
        "generated_at": _now(),
        "mode": ("probe in %s" % ("a copied tree" if info.get("isolation") == "copy"
                                  else "a detached worktree")) + (" with --fix" if fix else ""),
        "isolation": info.get("isolation"),
        "input_hash": ranked.get("input_hash"),
        "suite": suite,
        "fix": fix,
        "clusters": records,
        "counts": counts,
        "note": ("reproduced means a probe failed because of the defect. fixed means the same probe "
                 "passed after the patch. Neither means the patch is correct, only that it moved "
                 "this test from red to green."),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "verify.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print("pareto-triage %s — verify" % VERSION)
    print("isolation  %s" % ("copied tree (no git)" if info.get("isolation") == "copy"
                              else "detached worktree, removed afterwards"))
    print("suite      %s%s" % (suite["status"],
                               "" if suite.get("command") is None else ": %s" % suite["command"]))
    for record in records:
        print("  %-28s %-14s %s" % (record["cluster"], record["status"],
                                    record.get("reason") or ""))
    print("verified   %d fixed, %d reproduced, %d not reproduced, %d unverified, %d error"
          % (counts.get("fixed", 0), counts.get("reproduced", 0), counts.get("not-reproduced", 0),
             counts.get("unverified", 0), counts.get("error", 0)))
    print("")
    print("wrote %s" % target)
    return 0 if counts.get("error", 0) == 0 else 1


def cmd_calibrate(positional, flags):
    repo, out_dir = _paths(positional, flags)
    ranked_path = out_dir / "ranked.json"
    if not ranked_path.exists():
        print("no ranked.json in %s — run: pareto-triage rank <repo>" % out_dir, file=sys.stderr)
        return 2

    try:
        size = int(flags.get("sample", calibrate.MIN_SAMPLE))
        seed = int(flags.get("seed", 0))
    except (TypeError, ValueError):
        print("--sample and --seed must be integers", file=sys.stderr)
        return 2

    ranked = json.loads(ranked_path.read_text(encoding="utf-8"))
    findings = [f for f in ranked.get("findings", []) if f.get("class") == "failure-mode"]
    if not findings:
        print("no failure-mode findings to calibrate; calibration judges phase 2 only",
              file=sys.stderr)
        return 1

    sample_path = out_dir / "calibration.jsonl"
    summary_path = out_dir / "calibration.json"

    if sample_path.exists() and flags.get("fresh"):
        sample_path.unlink()

    if not sample_path.exists():
        picked = calibrate.sample(findings, size=size,
                                  repo_name=ranked.get("repo_name", ""), seed=seed)
        sample_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                                       for r in calibrate.rows(picked)), encoding="utf-8")

    records, bad = calibrate.read_verdicts(sample_path.read_text(encoding="utf-8"))
    summary = calibrate.summarise(records)
    summary.update({"seed": seed, "prompt": ranked.get("prompt"),
                    "tool_version": VERSION,
                    "generated_at": _now(), "unreadable_lines": bad})
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("pareto-triage %s — calibrate" % VERSION)
    print("sample     %s (%s filled)" % (sample_path, summary["filled"]))
    print("precision  %s within %s checked, threshold %.2f"
          % (summary["precision"] if summary["precision"] is not None else "unknown",
             summary["filled"], summary["threshold"]))
    print("status     %s" % summary["status"])
    if summary["status"] == "incomplete":
        print("")
        print("fill in each verdict in %s (true/false), then run this again." % sample_path)
    print("")
    print("wrote %s" % summary_path)
    return 0 if summary["status"] != "fail" else 1


def cmd_validate(positional, flags):
    if not positional:
        print("usage: pareto-triage validate <findings.jsonl> [--repo <path>]", file=sys.stderr)
        return 2
    path = Path(positional[0]).resolve()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        print("cannot read %s" % path, file=sys.stderr)
        return 2

    repo = Path(flags["repo"]).resolve() if "repo" in flags else path.parent.parent
    files = walk(repo)["files"]
    sources = {f["rel"]: f["text"] for f in files} or None

    current = prompts.identity()
    expected_hash = flags.get("prompt-hash") or current["hash"]

    cap = flags.get("max-confidence")
    if cap is not None and cap not in ("high", "med", "low"):
        print("--max-confidence must be high, med, or low", file=sys.stderr)
        return 2

    context_path = flags.get("context")
    if context_path in (None, True):
        context_path = path.parent / "context.jsonl"
    sites = load_sites(context_path)
    if sites is None and flags.get("strict-context"):
        print("--strict-context set but no context.jsonl at %s" % context_path, file=sys.stderr)
        return 2

    records, bad = parse_jsonl(text)
    rejected = list(bad)

    seen_ids = {}
    for line, record in records:
        if isinstance(record, dict) and record.get("id"):
            seen_ids.setdefault(record["id"], []).append(line)
    for record_id, lines in seen_ids.items():
        if len(lines) > 1:
            for line in lines:
                rejected.append((line, "duplicate id %s (also on line %s)"
                                 % (record_id, ", ".join(str(n) for n in lines if n != line))))

    for line, record in records:
        errors = validate_finding(record, sources=sources)
        if isinstance(record, dict) and record.get("class") == "failure-mode" and record.get("effort") is not None:
            errors.append("effort is derived by rank from the rubric; remove it from the record")
        if sites is not None and isinstance(record, dict) and record.get("class") == "failure-mode":
            site_id = record.get("site_id")
            site = sites.get(site_id)
            if not site_id:
                errors.append("site_id is required when context.jsonl is present")
            elif site is None:
                errors.append("site_id %s is not in context.jsonl" % site_id)
            else:
                if record.get("file") != site.get("file"):
                    errors.append("file %s does not match site %s (%s)"
                                  % (record.get("file"), site_id, site.get("file")))
                elif record.get("line") is not None and not site_contains(site, record["line"]):
                    errors.append("line %s is outside site %s (%s-%s)"
                                  % (record.get("line"), site_id, site["lines"][0], site["lines"][1]))
                elif isinstance(record.get("evidence"), str):
                    from lib.schema import _squash
                    if _squash(record["evidence"]) not in _squash(site.get("source") or ""):
                        errors.append("evidence is not inside site %s; it may be elsewhere in the file"
                                      % site_id)
        if cap and isinstance(record, dict):
            order = {"low": 0, "med": 1, "high": 2}
            if order.get(record.get("confidence"), 0) > order[cap]:
                errors.append("confidence %s exceeds the cap %s"
                              % (record.get("confidence"), cap))
        if errors:
            rejected.append((line, "; ".join(errors)))

    unstamped = 0
    for line, record in records:
        if not isinstance(record, dict) or record.get("class") != "failure-mode":
            continue
        stamp = (record.get("prompt") or {}).get("hash")
        if not stamp:
            unstamped += 1
        elif expected_hash and stamp != expected_hash:
            rejected.append((line, "prompt hash %s does not match %s: findings from different prompts are not comparable"
                             % (stamp, expected_hash)))

    valid = len(records) - (len(rejected) - len(bad))
    print("pareto-triage %s — validate" % VERSION)
    print("file       %s" % path)
    print("records    %d parsed, %d valid, %d rejected" % (len(records), valid, len(rejected)))
    print("prompt     %s" % (expected_hash or "unknown"))
    if unstamped:
        print("warning    %d record(s) carry no prompt hash; comparable only to the current prompt" % unstamped)
    if sources is None:
        print("warning    no source files found for this repo; evidence check skipped")
    for line, error in rejected[:25]:
        print("  line %d: %s" % (line, error))
    if len(rejected) > 25:
        print("  … %d more" % (len(rejected) - 25))
    if not records and not bad:
        print("note       empty input is a valid result: nothing applied at these sites")
    return 0 if not rejected else 1


def usage():
    print("""pareto-triage %s

usage: pareto-triage <command> [args]

  gate <repo> [--min-loc N] [--out DIR]   phase 0 — scope, refusal, entrypoints
  context <repo> [--limit N] [--max-depth N]  phase 0b — reachable candidate sites
          [--sample-order random|ranked] [--seed N]  how the cap is filled (default random)
          [--all] [--save-candidates PATH]  also write the whole candidate population
  sampling <repo> [--limit N] [--seed N]  compare selected sites against a random sample
  detect <repo> [--max-depth N]           phase 1 — built-in defect rules
  calibrate <repo> [--sample N] [--seed N] [--fresh]  measure phase 2 precision
  validate <findings.jsonl> [--repo P]    schema + hallucination guard for phase 2 output
                              [--context FILE] [--strict-context]
                              [--prompt-hash H] [--max-confidence high|med|low]
  rank <repo> [--require-coverage N]      phase 3 — score, cluster, shape
                              [--strict] [--budget S,M,L] [--trust-model-effort]
  report <repo> [--allow-stale] [--open]  phase 4 — html + json
  verify <repo> [--suite CMD] [--limit N] phase 5 — reproduce top clusters with probes
                              [--fix patch.diff] [--keep-worktree]
                              [--scaffold] [--install] [--probe-timeout N] [--suite-timeout N]
  version                                 print version
""" % VERSION)


def main(argv):
    if not argv:
        usage()
        return 2
    command, rest = argv[0], argv[1:]
    positional, flags = parse_args(rest)

    if command == "gate":
        return cmd_gate(positional, flags)
    if command == "context":
        return cmd_context(positional, flags)
    if command == "sampling":
        return cmd_sampling(positional, flags)
    if command == "detect":
        return cmd_detect(positional, flags)
    if command == "validate":
        return cmd_validate(positional, flags)
    if command == "calibrate":
        return cmd_calibrate(positional, flags)
    if command == "rank":
        return cmd_rank(positional, flags)
    if command == "report":
        return cmd_report(positional, flags)
    if command == "verify":
        return cmd_verify(positional, flags)
    if command in ("version", "--version", "-v"):
        print(VERSION)
        return 0
    if command in ("help", "--help", "-h"):
        usage()
        return 0
    print("unknown command: %s\n" % command, file=sys.stderr)
    usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
