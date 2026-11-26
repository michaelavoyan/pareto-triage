# Agent rules

Trunk-based development, adapted for one maintainer and a Python CLI. These
rules are enforceable; `CONTRIBUTING.md` is the human version.

## Branches

- Trunk is `main`. Every change reaches it through a short-lived branch, never a
  direct push to `main`.
  Source: https://trunkbaseddevelopment.com/ — "collaborate on code in a single branch called 'trunk'".
- One branch per task, one writer. Do not open a second branch for the same task,
  and do not let two agent sessions work on one branch.
  Source: https://trunkbaseddevelopment.com/short-lived-feature-branches/ — "the developer count should stay at one", one branch in flight per developer.
- A branch lives hours. Hard limit: two days from first commit to merge.
  Source: https://trunkbaseddevelopment.com/short-lived-feature-branches/ — "the branch should only last a couple of days".
- Delete the branch after merge. Do not reuse a merged branch.
  Source: https://trunkbaseddevelopment.com/short-lived-feature-branches/ — branches are "merged back in its own right" and deleted.
- Merge or rebase `main` into the branch before merging. Never merge one
  feature branch into another, and never merge a part-complete branch to `main`.
  Source: https://trunkbaseddevelopment.com/short-lived-feature-branches/ — "Breaking the contract" items 1, 2 and 4.

## Integration size

- Merge to `main` at least once every 24 hours.
  Source: https://trunkbaseddevelopment.com/continuous-integration/ — team members "commit to trunk at least once every 24 hours".
- If a change cannot land in a day, split it: ship the refactor, then the
  behaviour. Put the unfinished part behind a default-off flag (see below).
  Source: https://trunkbaseddevelopment.com/short-lived-feature-branches/ — one PR per refactor, then one per feature, rather than one PR per story.
- Ceiling: 400 changed lines per PR, counting additions plus deletions and
  excluding `fixtures/`, `scripts/test/`, and test files. CI enforces this.
  Source: https://trunkbaseddevelopment.com/continuous-review/ — PRs are reviewed in minutes, so they must stay reviewable.
- Over 400: split by phase or layer and land the green part first. Do not add
  the `size:large` label yourself; a maintainer applies it, and it raises the
  cap to 1,200 but does not waive it.
  Source: https://trunkbaseddevelopment.com/short-lived-feature-branches/ — "Keep each agent's change small" and integrate one at a time.

## Green trunk

- No merge while a required check is red or running. No merge with a red check,
  and no re-run to hide a flake.
  Source: https://trunkbaseddevelopment.com/fast-green-builds/ — the build must be "always green", verified before landing.
- Never skip, disable, delete, or weaken a test to get green. That includes
  `@unittest.skip`, commenting out assertions, and loosening a fixture's golden
  output.
  Source: https://trunkbaseddevelopment.com/fast-green-builds/ — watch for agents "disabling or deleting tests".
- Every behaviour change adds a test that fails on the base commit. Test and
  implementation go in the same PR.
  Source: https://trunkbaseddevelopment.com/fast-green-builds/ — "A test that has never been seen failing proves nothing".
- Before pushing, run both gates locally:
  `python -m unittest discover -s scripts/test` and
  `python scripts/check_rule_counts.py`.
  Source: https://trunkbaseddevelopment.com/continuous-integration/ — the pre-commit build is "the same one" CI runs.

## Releases

- A release is a `v*` tag on `main`, with `scripts/lib/version.py` matching the
  tag. Tags are the only release artifact.
  Source: https://trunkbaseddevelopment.com/release-from-trunk/ — teams release from the trunk, and a tag can stand in for a release branch.
- No `develop`, no `release/*`, no environment branches. The only branches are
  short-lived task branches.
  Source: https://trunkbaseddevelopment.com/branch-for-release/ — a release branch is cut "on a just in time basis" and deleted afterwards; long-lived shared branches are what trunk-based development rejects.
- No cherry-picks. Fix on `main` and re-tag. A maintenance branch exists only
  after a release line is declared in `CHANGELOG.md`; until then, fix forward.
  Source: https://trunkbaseddevelopment.com/branch-for-release/ — cherry-picks go "from the trunk to branch ONLY", and only when a release branch exists.

## Incomplete work

- Land incomplete work behind a default-off switch: a CLI flag
  (`--enable-<name>`), an environment variable, or a module constant
  `ENABLE_<NAME> = False`. The off path must be the current behaviour.
  Source: https://trunkbaseddevelopment.com/feature-flags/ — "Pushing code that's turned off into production" keeps trunk releasable while a feature is unfinished.
- No dead code, no commented-out blocks, no path that no flag or test can reach.
  If the code is behind a flag, the flag must actually select it.
  Source: https://trunkbaseddevelopment.com/feature-flags/ — decide the path once at the boot point rather than weaving `if`/`else` through the code.
- Document the flag where a user would look: `README.md` for user-facing
  switches, `references/` for rule or format changes. Record a "review for
  delete" date and remove the flag one release after it is fully on.
  Source: https://trunkbaseddevelopment.com/feature-flags/ — add flags to the readme "with a 'review for delete' date"; forgotten flags are tech debt.
- Every flag states its removal condition in the PR body and the CHANGELOG
  entry.
  Source: https://trunkbaseddevelopment.com/feature-flags/ — flags that never
  die become the `#ifdef` problem the site warns about.

## When blocked

Stop and report; do not work around a rule. State the branch age, the changed
line count, and the check that is failing. A branch older than one day or a diff
over the ceiling is split, not excused.
Source: https://trunkbaseddevelopment.com/short-lived-feature-branches/ — the two-day rule is a contract, not a target.
