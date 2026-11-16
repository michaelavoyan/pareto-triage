"""Phase 5: reproduce the top clusters with an executable probe.

The rule this module obeys: a finding is *verified* only when a test that
actually runs against the code fails because of the defect. Everything else is
unverified, and the report says so.

A probe is a script the agent or the user writes for one cluster, placed at
`out/probes/<cluster-key>.<py|sh|js|mjs|ts>`. Exit 0 means "the defect did not
reproduce"; any non-zero exit means "reproduced". Probes run inside a detached
git worktree, never in the user's working tree.

This does not prove a fix works. It proves the defect is real.
"""

import hashlib
import os
import re
import shutil
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import probes

PROBE_RUNNERS = {
    ".py": ["python3"],
    ".sh": ["sh"],
    ".js": ["node"],
    ".mjs": ["node"],
}

# TypeScript has no runtime of its own. First available wins; all missing is a
# named reason, not a crash.
TS_RUNNERS = [["npx", "--no-install", "tsx"], ["npx", "--no-install", "ts-node"]]

INSTANT_FAILURE_SECONDS = 0.05

PROBE_TIMEOUT_DEFAULT = 120
SUITE_TIMEOUT_DEFAULT = 600
TAIL_CHARS = 2000


def probe_slug(key):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(key)).strip("-") or "cluster"


def resolve_runner(path, worktree):
    """Return (argv, reason). argv is None when nothing can run the probe."""
    suffix = Path(path).suffix
    if suffix in PROBE_RUNNERS:
        return PROBE_RUNNERS[suffix], None
    if suffix != ".ts":
        return None, "no runner known for %s" % suffix

    local = Path(worktree) / "node_modules" / ".bin"
    for candidate in TS_RUNNERS:
        if candidate[0] == "npx":
            tool = candidate[-1]
            if (local / tool).exists():
                return [str(local / tool)], None
            if shutil.which(tool):
                return [tool], None
    return None, "no TypeScript runner available (tried tsx, ts-node in node_modules/.bin and PATH)"


def find_probe(probes_dir, key):
    slug = probe_slug(key)
    for ext in PROBE_RUNNERS:
        candidate = probes_dir / (slug + ext)
        if candidate.exists():
            return candidate
    return None


def run_command(argv, cwd, timeout):
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, env=_child_env())
        output = (proc.stdout or "") + (proc.stderr or "")
        return {
            "exit": proc.returncode,
            "duration": round(time.time() - started, 2),
            "timed_out": False,
            "output_tail": output[-TAIL_CHARS:],
        }
    except subprocess.TimeoutExpired:
        return {
            "exit": None,
            "duration": round(time.time() - started, 2),
            "timed_out": True,
            "output_tail": "timed out after %ss" % timeout,
        }
    except OSError as exc:
        return {
            "exit": None,
            "duration": 0.0,
            "timed_out": False,
            "output_tail": "cannot execute: %s" % exc,
        }


def _child_env():
    env = dict(os.environ)
    # Keep probes offline and non-interactive. Not a security boundary.
    env.setdefault("CI", "1")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _copy_tree(repo):
    """Copy the tree without .git, out, or build directories. Weaker isolation."""
    from .walk import IGNORE_DIRS

    skip = set(IGNORE_DIRS) | {".git", "out"}
    path = Path(tempfile.mkdtemp(prefix="pareto-triage-copy-"))
    target = path / "tree"
    try:
        shutil.copytree(str(repo), str(target),
                        ignore=shutil.ignore_patterns(*sorted(skip)),
                        symlinks=True)
    except OSError as exc:
        shutil.rmtree(str(path), ignore_errors=True)
        return None, {"ok": False, "reason": "cannot copy the tree: %s" % exc}
    return target, {"ok": True, "path": str(target), "parent": str(path), "isolation": "copy"}


def make_worktree(repo, timeout=120):
    """Isolated checkout: a detached git worktree, or a copy when there is no git."""
    probe = run_command(["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
                        repo, timeout=30)
    in_git = probe["exit"] == 0 and "true" in probe["output_tail"]

    if in_git:
        head = run_command(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"], repo, timeout=30)
        if head["exit"] == 0:
            path = Path(tempfile.mkdtemp(prefix="pareto-triage-verify-"))
            target = path / "tree"
            add = run_command(["git", "-C", str(repo), "worktree", "add", "--detach",
                               str(target), "HEAD"], repo, timeout=timeout)
            if add["exit"] == 0:
                return target, {"ok": True, "path": str(target), "parent": str(path),
                                "isolation": "worktree"}
            shutil.rmtree(str(path), ignore_errors=True)

    return _copy_tree(Path(repo))


def remove_worktree(repo, worktree, info):
    if worktree is None:
        return
    if info.get("isolation") == "worktree":
        run_command(["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
                    repo, timeout=60)
    if info.get("parent"):
        shutil.rmtree(info["parent"], ignore_errors=True)


def verify_clusters(repo, ranked, probes_dir, worktree, limit=3, timeout=PROBE_TIMEOUT_DEFAULT):
    """Return a list of per-cluster verification records."""
    records = []
    for cluster in ranked.get("clusters", [])[:limit]:
        key = cluster.get("key")
        probe = find_probe(probes_dir, key) if probes_dir else None
        record = {
            "cluster": key,
            "taxonomy": cluster.get("taxonomy"),
            "class": cluster.get("class"),
            "n_sites": cluster.get("n_sites"),
            "priority": cluster.get("priority"),
            "main_site": "%s:%s" % (cluster.get("file"), cluster.get("line")),
            "status": "unverified",
            "probe": None,
            "exit": None,
            "duration": None,
            "output_tail": None,
        }
        if probe is None:
            record["reason"] = "no probe at out/probes/%s.<ext>" % probe_slug(key)
            records.append(record)
            continue

        if probes.is_unfilled(probe.read_text(encoding="utf-8", errors="replace")):
            record["probe"] = str(probe)
            record["status"] = "unverified"
            record["reason"] = "probe is an unfilled scaffold"
            records.append(record)
            continue

        runner, reason = resolve_runner(probe, worktree)
        if runner is None:
            record["status"] = "error"
            record["probe"] = str(probe)
            record["reason"] = reason
            records.append(record)
            continue

        record["probe"] = str(probe)
        result = run_command(runner + [str(probe)], worktree, timeout)
        record["exit"] = result["exit"]
        record["duration"] = result["duration"]
        record["output_tail"] = result["output_tail"]
        if result["timed_out"]:
            record["status"] = "error"
            record["reason"] = "probe did not finish within %ss" % timeout
        elif result["exit"] is None:
            record["status"] = "error"
            record["reason"] = result["output_tail"]
        elif result["exit"] != 0:
            record["status"] = "reproduced"
            if result["duration"] < INSTANT_FAILURE_SECONDS and not (result["output_tail"] or "").strip():
                record["suspicious"] = "instant failure with no output"
                record["reason"] = "exited immediately with no output; check the probe is not failing to start"
        else:
            record["status"] = "not-reproduced"
            record["reason"] = "probe exited 0: the defect did not reproduce"
        records.append(record)

    return records


def suite_command(scope):
    """Return an argv for the detected test runner, or None.

    Best effort: a fresh worktree has no installed dependencies, so this often
    cannot run. That is recorded, never papered over.
    """
    tests = scope.get("tests") or {}
    runner = tests.get("runner")
    return {
        "pytest": ["python3", "-m", "pytest", "-q"],
        "vitest": ["npx", "--no-install", "vitest", "run"],
        "jest": ["npx", "--no-install", "jest", "--ci"],
        "mocha": ["npx", "--no-install", "mocha"],
        "node:test": ["node", "--test"],
    }.get(runner)


def apply_patch(worktree, patch_path):
    """Apply a patch inside the worktree only. Returns a record, never raises."""
    patch = Path(patch_path)
    if not patch.exists():
        return {"applied": False, "reason": "patch not found: %s" % patch}

    def record(method, files):
        return {"applied": True, "method": method, "patch": str(patch),
                "sha256": hashlib.sha256(patch.read_bytes()).hexdigest()[:16],
                "files": sorted(files)[:20]}

    check = run_command(["git", "apply", "--check", str(patch)], worktree, timeout=60)
    if check["exit"] == 0:
        applied = run_command(["git", "apply", str(patch)], worktree, timeout=60)
        if applied["exit"] != 0:
            return {"applied": False, "reason": "git apply failed: %s" % applied["output_tail"][-300:]}
        status = run_command(["git", "status", "--porcelain"], worktree, timeout=60)
        files = [line[3:] for line in (status["output_tail"] or "").splitlines() if line.strip()]
        return record("git apply", files)

    if not shutil.which("patch"):
        return {"applied": False, "reason": "patch does not apply, and no `patch` command to try"}

    dry = run_command(["patch", "-p1", "--dry-run", "-i", str(patch)], worktree, timeout=60)
    if dry["exit"] != 0:
        return {"applied": False, "reason": "patch does not apply: %s" % dry["output_tail"][-300:]}
    result = run_command(["patch", "-p1", "-i", str(patch)], worktree, timeout=60)
    if result["exit"] != 0:
        return {"applied": False, "reason": "patch failed: %s" % result["output_tail"][-300:]}

    touched = re.findall(r"^patching file (.+)$", result["output_tail"] or "", re.M)
    return record("patch -p1", touched)


def compare(before, after):
    """Turn two probe runs into the rubric's verified/inconclusive vocabulary."""
    if before is None or after is None:
        return "unverified", "probe did not run on both sides of the patch"
    if before["exit"] == 0:
        return "not-reproduced", "the probe passed before the patch: nothing to verify"
    if after["exit"] == 0:
        return "fixed", "the probe failed before the patch and passed after it"
    return "inconclusive", "the probe still fails after the patch"


def summarize(records):
    counts = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    return counts
