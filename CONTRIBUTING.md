# Contributing

This repo uses trunk-based development. `main` is the only long-lived branch;
everything lands there through a short-lived branch and a small pull request.

## The rules

1. **One branch per task, deleted after merge.** Name it `fix/...`, `feat/...`,
   `docs/...`, or `chore/...`. One writer per branch. Merge `main` into it before
   you finish; never merge two feature branches, and never merge a part-complete
   branch to `main`.
2. **Land within a day.** If it will not be done today, split it into a refactor
   PR now and a behaviour PR later. A branch that reaches two days old is a bug in
   the plan, not a milestone.
3. **Keep the diff under 400 changed lines** (additions + deletions, excluding
   `fixtures/`, `scripts/test/`, and test files). CI fails a larger PR. Split by
   phase; if a split is genuinely impossible, ask for the `size:large` label,
   which raises the cap to 1,200.
4. **Trunk stays green.** No merge while a required check is red. Do not skip,
   disable, or delete tests to pass; do not loosen a golden file to pass. The
   fix is a failing test plus the code that makes it pass, in the same PR.
5. **Releases are tags.** A release is a `v*` tag on `main` with a matching
   `scripts/lib/version.py`. No `release/*`, no `develop`, no environment
   branches. Fix bugs on `main` and re-tag; no cherry-picking unless a release
   line is declared in `CHANGELOG.md`.
6. **Incomplete work ships off.** Hide it behind a default-off CLI flag,
   environment variable, or `ENABLE_<NAME> = False` constant, keep the current
   behaviour as the default, remove the flag one release after it is fully on.
   No dead code and no commented-out blocks.

The reasoning and sources: `AGENTS.md`. The upstream model:
<https://trunkbaseddevelopment.com/>.

## Before you push

```sh
python -m unittest discover -s scripts/test
python scripts/check_rule_counts.py
```

CI runs those plus the end-to-end pipeline on `fixtures/express-app` and
`fixtures/python-app`.

## PR checklist

- [ ] One task, one branch, and the branch is under two days old.
- [ ] At most 400 changed non-test lines, or split already.
- [ ] Tests run green locally; CI green before merge.
- [ ] Every behaviour change has a test that fails without the change.
- [ ] Docs updated when user-visible behaviour, a rule, or a format changed.
- [ ] No release branch, no cherry-pick, no `develop`.
- [ ] Incomplete work is behind a default-off flag with a stated removal
      condition, or is not in this PR.
- [ ] Branch deleted after merge.

## Review

Small PRs are the point: they get read in minutes. A PR that cannot be read in
one sitting gets split, not rubber-stamped. Ask before starting anything that
looks like it will cross the ceiling.
