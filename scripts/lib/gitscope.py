"""Which files a secret scan may attribute to the repository.

A credential in an untracked, gitignored `.env` is not a committed secret: the
repository does not publish it. Reporting it is a false positive at blast 4, so
the config-secret rules read only the paths `git ls-files` reports as tracked
when the scanned tree sits inside a git work tree. Source-file secret rules are
not narrowed: a key hardcoded in a `.py` file is a finding whether or not that
file has been committed, because the code is what will be published.

When the commit set cannot be established — no git binary, not a repository, a
failing `ls-files` — the scan keeps the wider behaviour and says why. Silently
narrowing or silently widening the rule both misstate what was examined.
"""

import subprocess

TRACKED_REASON = ("inside a git work tree: config-secret rules read only files "
                  "`git ls-files` reports as tracked")
NOT_REPO_REASON = ("not inside a git work tree: commit status is unknown, so "
                   "every config file is scanned")
NO_GIT_REASON = ("git is not installed: commit status is unknown, so every "
                 "config file is scanned")


def _unavailable(reason):
    return {"tracked_only": False, "reason": reason, "tracked": set()}


def secret_scope(root):
    """Return {tracked_only, reason, tracked}.

    `tracked` holds repository-relative posix paths, matching the `rel` field
    of a walked file. It is empty when `tracked_only` is false and must not be
    read as "nothing is tracked" in that case.
    """
    try:
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True)
    except OSError:
        return _unavailable(NO_GIT_REASON)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return _unavailable(NOT_REPO_REASON)

    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True)
    except OSError:
        return _unavailable(NO_GIT_REASON)
    if listed.returncode != 0:
        detail = listed.stderr.decode("utf-8", "replace").strip()
        return _unavailable("git ls-files failed (%s): every config file is scanned"
                            % (detail or "exit %d" % listed.returncode))

    text = listed.stdout.decode("utf-8", "surrogateescape")
    tracked = {path for path in text.split("\0") if path}
    return {"tracked_only": True, "reason": TRACKED_REASON, "tracked": tracked}
