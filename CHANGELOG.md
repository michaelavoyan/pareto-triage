# Changelog

## 0.6.1

- F2: a top-five card now shows the evidence line with up to three lines either
  side, in a small monospace block with the cited line marked. The block is
  read from the source file when `report` runs and capped at seven lines, so
  the HTML stays one offline file. A missing file, an unreadable file, or a
  line out of range falls back silently to the quoted line alone: a report
  rendered away from its tree still quotes what the finding claimed, and
  nothing is invented to fill the block. Every row is escaped and redacted, so
  a secret on a neighbouring line is masked exactly like one on the cited line.
- CI: Python 3.15 joins the test matrix on `ubuntu-latest`, next to 3.9
  (`ubuntu-22.04`) and 3.12 (`ubuntu-latest`). `pipeline.yml` and `release.yml`
  already ran 3.15; this is the first time the whole suite does.
- README corrected: it now states what the detector tier measures. 26 rules,
  and on the two real corpora tested only the security rules produced
  anything — Signal-Android (828k lines) 1 finding, JobPilot (10k lines) 0
  after the secret rule was limited to committed files. The appendix's
  `0 hits (unexercised)` and `unmeasured` labels are named there so a zero is
  not read as coverage.

## 0.6.0

- Added `context --coverage F`: keeps `max(1, ceil(F × judgeable))` sites,
  seeded, instead of a fixed `--limit`, and refuses to run with both. The
  per-file cap is lifted in coverage mode, because a fraction is a share of the
  sites that exist; capping would make `--coverage 1` drop sites. `sample.json`
  records `{mode: "coverage", fraction, seed, population, kept, per_file,
  judgeable, judgeable_detail, strata}` and a limit run keeps the old fields
  with `mode` set to the sampling order.
- Both sampling modes now apportion seats by reach: every band present in the
  judgeable population gets a proportional share, and a band that exists gets
  at least one seat when the seat count allows. `strata` in `sample.json`
  records the seats each band actually received.
- Added `references/entrypoints.md` sections for the `sample.json` shape and
  the sample-size formula `n = 1.96² · p(1 − p) / 0.05²`. The default stays 400
  until `calibrate` supplies `p`; the formula is documented, not applied.
- Withdrew the `js-unvalidated-input` candidate after measurement. It fired on
  a `req.body.X`/`req.query.X`/`req.params.X` value reaching a DB or shell call
  in a route file, with validator and parsing silence. On JobPilot (`4cf86d0`,
  113 non-test files) it produced 0 findings: the server uses `createServer`
  with pathname cases and reads `body.X` after `JSON.parse`, not Express
  routes. On Signal-Android (`2dd5703`, 8,906 non-test files) it produced 0
  findings: none of the five non-test JS files is a route. Zero hits on both
  corpora means no hit to classify; 0/0 is not a pass. The firing and silent
  shapes stay as fixtures, asserted to produce no finding.
- Withdrew the `jvm-write-without-transaction` candidate after measurement. It
  fired on methods with two database writes and no transaction call in the
  body. On Signal-Android it produced 230 findings; every one was read: 5
  TRUE, 39 DELIBERATE, 186 FALSE — 2.17% true positives, and still only 19.1%
  if every DELIBERATE finding is counted as acceptable. The false positives are
  transactions the method does not contain: 120 framework `onCreate`/
  `onUpgrade`/migration methods, 45 `withinTransaction` calls, 7 caller
  `ensureInTransaction()` paths, 12 mutually exclusive branches, and 2 method
  declarations named `execSQL`. JobPilot has no JVM source, so incidence there
  was zero. The rule count returns to 26; the per-hit audit is in
  `references/defect-rules.md`.

## 0.5.0

- Withdrew the `js-sql-template` candidate before release. It was correct by
  construction: a template literal with `${…}` as the first argument to
  `query`/`execute`/`exec`/`raw` fired only on a database receiver or in a file
  importing a SQL driver, and only with no values argument. Measured on JobPilot
  (`37aceae`, 111 non-test files) and Signal-Android (`2dd5703`, 8,906 non-test
  files) it produced 0 findings on both: JobPilot's SQL is all `prepare`/`exec`
  with static text or `?` plus values, and Signal-Android has no
  TypeScript/JavaScript application SQL. With no finding to inspect its
  precision is unmeasured, and 0/0 is not a pass under the 0.70 true-positive
  gate — the same standard that withdrew `jvm-trust-all`. The two reporting and
  CI deliverables below ship; the rule does not. The silent shapes (parameter
  array, `?` placeholders, non-database receiver) stay in
  `fixtures/express-app/src/sql.ts`, asserted to produce no finding from any
  rule. The rule count is 26.
- Rejected the Kotlin string-template extension of `jvm-sql-injection` after
  measuring it: 12 findings on Signal-Android, all 12 deliberate identifier
  interpolation (table/column names, `$table`, `${index * 500}`), 0 true
  positives. The measurement and the hit list are in
  `references/defect-rules.md`; the shape is a fixture asserted silent.
- F1: `scope.json` and `ranked.json` now carry
  `rule_incidence: {rule: hits}`. `detect` records it in the scan artifact, and
  the report renders an appendix table of every shipped rule: hits in this
  scan, and precision from `out/calibration.json` when it exists, otherwise
  `unmeasured`. A rule that ran and found nothing reads `0 hits`; a rule whose
  language was absent reads `0 hits (unexercised)`.
- G1: `scripts/check_rule_counts.py` runs `gate` and `detect` on
  `fixtures/jvm-rules` and `fixtures/express-app` and compares per-rule counts
  with the checked-in `scripts/test/golden/rule-incidence.json`. A rule that
  silently stops firing — or stops running — fails the new `rule-incidence` CI
  job. Standard library only.

## 0.4.5

- Fixed two scope bugs found auditing the TypeScript rules against JobPilot.
  Both were rules claiming more than the tree proved.
- `cfg-secret-generic` read `.env` whether or not it was committed. JobPilot
  gitignores `.env` and `git ls-files` lists only `.env.example`, yet the scan
  reported a credential from `.env` at blast 4. Config-secret scanning is now
  limited to paths `git ls-files` reports as tracked when the scanned tree is
  inside a git work tree, and `scope.json` records
  `secrets: {tracked_only, reason}`. Source-file secret rules are unchanged: a
  key hardcoded in source is a finding whether or not the file is committed.
  With no git binary, no repository, or a failed `ls-files`, every config file
  is scanned and the reason is recorded.
- `js-exec-interp` fired on any `exec(` with an interpolated template, so
  ``db.exec(`SELECT … ${id}`)`` in a `node:sqlite` file was command injection at
  blast 5. It now requires the file to import `child_process` and the call to
  be `exec` or `execSync`. `execFile`/`execFileSync` fire only when the matched
  line also passes `shell: true`. `spawn`/`spawnSync` are no longer matched:
  without `shell: true` they take an argument vector, not a shell string. The
  two resulting false negatives (`spawn` with `shell: true`, `execFile` with
  the option on a later line) are recorded in `references/defect-rules.md`.
- Fixtures: a git repo with a tracked `.env` (fires), the same bytes untracked
  (silent, counted as skipped), an untracked source file holding a key (fires),
  a non-git tree and a missing-git tree (fire, with the reason recorded), plus
  the `node:sqlite` / `child_process` JavaScript pair.
- Measured on JobPilot: `detect` returns 0 findings, down from 1
  (`cfg-secret-generic` in the untracked `.env`), reported as
  `secrets    git-tracked config files only, N untracked skipped`. Measured
  on Signal-Android at `8959dc6`: still 1 finding (`jvm-weak-hash`), no
  regression.

## 0.4.4

- Withdrew `jvm-empty-catch`. An audit of all 60 findings on Signal-Android at
  `8959dc6` found 0 true positives: 55 were deliberate cleanup, optional
  work, or parse/validation control flow, and 5 were mechanically false. The
  rate is 0/60, so the rule cannot hold the defect tier; the reason is that
  whether a catch may swallow is intent, and intent is not line-local. The
  measurement is recorded in `references/defect-rules.md` under "Considered
  and rejected".
- Fixed the literal masking that produced the 5 false positives. A catch body
  that is a string literal or template (`""`, `"Unknown"`, `"Error: ${e}"`)
  was blanked to whitespace and read as an empty body. Masking now keeps the
  opening quote, so a literal is still a body and a comment still is not. The
  five Signal shapes are fixtures, and the helper is tested on each.
- `jvm-weak-hash` blast is 3, not 4. Detection is certain, severity is
  contextual: MD5 as a bucketing or dictionary key has no integrity role. A
  `WeakHashBucketing` fixture records that shape and is expected to fire.
- `detect` prints per-rule incidence: every rule that ran, with its hit count
  in this scan. A rule at 0 was exercised and found nothing; a rule missing
  from the line never ran because no file of its language was scanned. "0
  findings" is now visibly unexercised rather than clean.
- The rule count is 26 in README, `SKILL.md`, and `references/defect-rules.md`,
  matching `META`. `swallowed-exception` is a failure-mode taxonomy only;
  `DEFECT_TAXONOMIES` no longer lists it.
- Measured on Signal-Android at `8959dc6`: `detect` returns 1 finding
  (`jvm-weak-hash`), down from 61 (60 empty catch, 1 weak hash). The five
  false shapes produce nothing.

## 0.4.3

- Removed `jvm-log-only-catch` and `jvm-http-no-timeout`. Both had been
  measured and rejected before 0.4.2 — 0/4 precision and ~25% — and 0.4.2
  shipped them as active anyway. That was a release error, not a judgment
  call: the two rules added 349 findings to Signal-Android, buried the 61 that
  the other rules prove, and made `references/defect-rules.md` list each of
  them twice, once as active and once as rejected. 0.4.3 withdraws the
  release's headline change rather than repairing it.
- The JVM detector is back to five rules: `jvm-exec-injection`,
  `jvm-sql-injection`, `jvm-empty-catch`, `jvm-weak-hash`, and
  `jvm-object-input-stream`. `missing-timeout` is a failure-mode taxonomy
  again, not a defect taxonomy, because no defect rule emits it. The fixtures
  and firing tests added for the two rules are gone; the log-then-throw and
  log-then-return fixtures stay as silent cases for `jvm-empty-catch`.
- README, `SKILL.md`, and `references/defect-rules.md` state 27 rules, and a
  drift test now compares every stated count and the active rule table with
  `META`, so a rule cannot be documented as active and rejected at once.
- Measured on Signal-Android at `8959dc6`: `detect` returns 61 findings —
  60 `jvm-empty-catch` and 1 `jvm-weak-hash` — down from 410 (60 empty catch,
  345 log-only catch, 4 no-timeout, 1 weak hash). The pre-0.4.2 detector run
  on the same tree returns the identical 61 findings at the same lines, so
  the removal restores the baseline exactly. The 63 figure recorded when the
  rules were rejected does not reproduce on this tree; 61 is the measured
  baseline.

## 0.4.2

- Two JVM rules read past the line that matched. `jvm-http-no-timeout` fires on
  an `OkHttpClient.Builder()` or `HttpClient.newBuilder()` constructed in the
  expression whose statement sets no `callTimeout`, `readTimeout`,
  `writeTimeout`, `connectTimeout`, or `.timeout(`. The expression follows Java
  to the top-level `;` and Kotlin through a chained call on the next line. A
  builder supplied by a variable or a parameter stays silent: absence is not
  visible in the expression. `missing-timeout` is now a defect taxonomy as well
  as a failure-mode one.
- `jvm-log-only-catch` fires on a `catch` whose every top-level statement is a
  logging or printing call, using the same brace matcher as `jvm-empty-catch`.
  A `throw`, `return`, `break`, `continue`, any non-log statement, or an
  unbalanced block silences it. `jvm-empty-catch` does not also fire on a
  log-only body.
- Fixtures pin one firing and one silent case per rule, plus a builder supplied
  as a parameter and log-then-throw / log-then-return shapes. `jvm-http-no-timeout`
  is covered on Java and Kotlin, including a timeout on the next chain line.
- Measured on Signal-Android: 63 findings before, 408 after. `jvm-http-no-timeout`
  produced 4, all OkHttp builders. OkHttp applies 10s connect/read/write
  defaults, and one of the four (`SignalRestClient`'s base client) is given its
  timeouts later in `newCallClient`, so the rule puts a shape claim at the top
  of the board rather than a proven hang. `jvm-log-only-catch` produced 341
  findings, 5.4x the previous total; the inspected sample is mostly deliberate
  best-effort handling (codec release, stream close, optional UI), which
  `references/taxonomy.md` calls not a finding. Read both counts as shapes to
  judge, not as defect totals.

## 0.4.1

- The shape verdict now says what carries it. `ranked.json` gains
  `attribution`, splitting total impact and the C20 top fifth by class
  (`defect` from rules, `failure_mode` from judgment), with cluster and finding
  counts and a verdict computed on each class alone. The Shape section prints a
  second sentence next to the verdict: "62% of the concentration comes from rule
  findings, 38% from judgment", or "All of the concentration comes from rule
  findings; judgment produced no clusters" when a class is empty. When judgment
  exists but would be `insufficient` on its own, the report adds "Judgment alone
  would be insufficient at 2 clusters; this verdict is carried by 62 rule
  findings." A verdict produced by rule clusters is never presented as a model
  conclusion. Calibrated on Signal-Android: 200 judged sites, 3 ranked findings,
  and a verdict carried by the 62 `jvm-empty-catch` rule hits rather than by
  judgment.
- `jvm-sql-injection` and `jvm-exec-injection` no longer fire on shapes that
  only look like injection. `execute(` is a name shared by SQL statements,
  executors, and callbacks, so the SQL rule now also requires a statement verb
  (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `REPLACE INTO`) inside the call;
  `keyedExecutor.execute("Call::" + id, …)` is quiet. The exec rule now
  requires a `+` operand that is not a compile-time constant: lowercase names,
  fields, parameters, array elements, and calls count as values, while
  `UPPER_SNAKE_CASE` constants (`FILTER_SPEC`, `BuildConfig.ENDPOINT`), quoted
  literals, and numbers do not. `exec("logcat -d " + FILTER_SPEC)` is quiet;
  `exec("convert " + path)` still fires. Both rules now ignore calls inside
  string literals, not only behind a comment marker. Fixture pairs pin the two
  false-positive shapes next to the planted defects.
- `detect` skips test files with the same `is_test_path` predicate `context`
  uses, and prints the count (`files 9,401 scanned, 581 skipped as test code`).
  Test code is not on the request path; a rule finding there cannot be fixed by
  a change that moves the product. On Signal-Android this removed 9 of 74
  findings, all under `/test/` and `/androidTest/`.
- `context` samples judgeable sites only: at least four non-blank body lines
  and at least one failure surface (`try`/`catch`, `await`/`suspend`/
  `withContext`, a network call, a DB write, or a loop). The filter runs in the
  sampling step, never on `--all`: `candidates.jsonl` still holds every
  candidate, with the selected sites as its prefix. When fewer judgeable sites
  exist than the limit, the cap is filled from the non-judgeable remainder in
  ranked order and the fallback is printed. `sample.json` gains
  `judgeable: {candidates, filtered, fallback}`. On Signal-Android the first
  200 selected sites go from 37 with a failure surface (18.5%) and a median
  body of 6 lines to 200 (100%) and 15 lines, with 56 three-line-or-shorter
  sites removed; the population stays 20,768 and the judgeable share of it is
  20.9%.

## 0.4.0

- `detect` reports rule coverage instead of leaving a zero finding count to be
  read as clean. It prints one line per scanned language (`swift 0/9 files (no
  rules)`), and when a supported language has files but no detector it prints
  `no rules were applied to 9 files of Swift — these files are unassessed, not
  clean`. `scope.json` records the same data in `rule_coverage.by_language`
  (`files`, `files_with_rules`, `rules`), `ranked.json` copies it and writes
  `no rules were applied to 9 files of Swift: the tool has no Swift defect
  rules, so this report says nothing about defects in them.` into
  `could_not_determine`. The check is derived from the extension-to-rule table,
  not from a Swift special case, so a language added later without rules is
  reported the same way. Measured on Signal-iOS, where `detect` used to print
  `findings 0` for 705k lines of Swift.
- Swift and Objective-C call sites now count toward effort. `SOURCE_EXTS` was
  missing `.swift`, `.m`, and `.mm`, so a failure mode in those languages got
  only its file and no mentions; a Swift finding with six call sites now scores
  effort 2 instead of the floor. Fixture coverage asserts the rise, not the
  constant.
- A shape verdict needs at least three clusters. With one cluster C20 is 1.0 by
  arithmetic and the report used to print `shortcut` while `pareto.shortcut`
  was false; with two it is whichever cluster is larger. `shape.verdict` is now
  `insufficient`, `shape.c20` stays a number, `shape.n_clusters` and
  `shape.min_clusters` state the count and the threshold, the report says the
  verdict is not meaningful at that cluster count, the effort ladder is
  omitted, and every `pareto`/`pareto_ladder` row reports `shortcut: false`.
  `references/rubric.md` documents the threshold. Measured on the 2-cluster
  express fixture, which used to print `shortcut` at C20 60%.
- README and `references/entrypoints.md` state the iOS limit as measured:
  Swift/Objective-C support is reachability and site extraction only, there are
  no defect rules for them, Swift reachability needs a same-target type mention
  so a separate framework target such as SignalServiceKit is unreachable
  (1,311 files at reach 1, 44% of the code), and the 200-site calibration on
  Signal-iOS produced one cosmetic finding.

- `context` extracts Swift and Objective-C sites instead of refusing on an iOS
  repo. Swift `func`/`init`/`deinit` and computed `var` bodies are sites; a type
  body is a site only when nothing inside it is, so a class collapses into its
  methods and properties. Objective-C `-`/`+` methods are sites, with or without
  a wrapped signature; `@implementation` is a container, never judged, and each
  method names it in `enclosed_by`. Bounds survive `"""…"""` multi-line strings,
  `#"…"#`/`##"…"##` raw strings, `\(…)` interpolation — including a string or
  closure inside the interpolation — `@"…"` strings, and `^{…}` block literals.
  On Signal-iOS every file at reach ≥ 2 is Swift, so the old extractor returned
  no candidate at all and `context` refused with `no candidate sites`; the same
  run now yields 17,457 candidates from 158 reachable files, 200 of them kept at
  `--limit 200`. All 200 start on a declaration line: 136 function declarations,
  9 attribute-headed functions, 44 computed properties, 11 type bodies. 22 of the
  200 (11%) contain `try`, `catch`, `await`, or a network call, against 7% of the
  population, so phase 2 has something to judge on this repo. Objective-C is
  measured on fixtures only: the tree has 34 `.m` files and none of them reaches
  2.
- Entrypoints come only from a language that carries the repo. A language must
  hold at least 5% of the supported non-blank lines for its entrypoints to
  count; below that they are ignored and named in a gate warning. Before this,
  Signal-iOS passed the gate on 39 CLI entrypoints from 22 bundled Python files
  while 705k lines of Swift supplied none. If the filter leaves nothing, the
  gate refuses and says every entrypoint came from a language under the floor.
  A `package.json` `bin` names no lines of its own, so the share test does not
  apply to manifest entrypoints. No repo is special-cased.
- `import Module` is no longer a Swift edge. Matching a module import to that
  target's files produced 1,693,481 edges on Signal-iOS — 97% of the graph —
  and carried no information about which file calls which. Same-target type
  mentions (57,924 edges) and Objective-C `#import` remain. `reach_meta.swift`
  now reports `module_edges: 0` and `module_edge_rule: "dropped"`.
- An Objective-C `#import` whose path does not resolve now takes a basename
  that exactly one scanned file carries; two or more files with that basename
  leave it unresolved. Fallbacks and ambiguities are counted in
  `reach_meta.objc`. Measured on Signal-iOS: +88 resolutions, 0 ambiguous.
- Swift and Objective-C have entrypoints: `@main`, `@UIApplicationMain`, and
  `UIApplicationMain(` seed `ui`/5 as `MAIN`; conformance to
  `UIApplicationDelegate`, `AppDelegate`, or `SceneDelegate` seeds `app`/3 as
  `APPDELEGATE Class`; `UIViewController`/`UIView` subclasses, directly or
  through four hops of project bases, seed `ui`/5 as `VIEWCONTROLLER Class`.
  ObjC `@interface X : UIViewController` seeds the scanned implementation.
  `@IBAction` handlers are not seeded separately: the controller already covers
  the file.

- Swift and Objective-C are languages the tool knows. `.swift` and `.m`/`.mm`
  count as supported code; a header does not. `.h` is an import target only, so
  it is never a graph node and never a counted line — counting it would double
  every Objective-C size figure. `#import "A/B.h"`, `#import <A/B.h>`, and
  `#import "B.h"` resolve against the scanned tree by trailing path, with the
  JVM resolver's tiebreak (shallower path, then lexical), and an edge that lands
  on a header is recorded against its `.m`/`.mm` because the pair is one
  logical file. Headers that name a framework namespace — `<SignalServiceKit/
  OWSReadTracking.h>` for a file at `SignalServiceKit/Messages/OWSReadTracking.h`
  — stay unresolved: that lookup needs the framework's header map, not a
  path suffix.
- Swift gets reachability from `project.pbxproj`, not from imports. Target
  membership is read from the Sources build phases and from Xcode 16
  synchronised root groups (empty Sources phase, folder compiled wholesale,
  membership exceptions honoured). Two Swift files are neighbours only when
  they are in the same target *and* the importer names a type the other
  declares. With no project file the run reports that it has no intra-target
  edges rather than guessing. On Signal-iOS the graph resolves 2,698 of 2,720
  Swift files into 8 targets and 57,924 mention edges.
- `consume(` is narrowed to a queue signal. It counts only when the receiver
  names `consumer`, `queue`, or `subscription`, or the line contains `topic`,
  `queueName`, or `partition`. On Signal-Android all 27 remaining consumer
  seeds were Compose pointer `consume()` calls in gesture code. The cost: an
  AMQP `channel.consume(` with a bare receiver is no longer a seed.
- Android components are entrypoints. `ui` (seed 5) covers classes extending
  `Activity`, `AppCompatActivity`, `ComponentActivity`, `FragmentActivity`, or
  `Fragment`; `background` (4) covers `Service`, `IntentService`, `JobService`,
  `Worker`, `BroadcastReceiver`, `ContentProvider`; `app` (3) covers
  `Application`. Details name the component. A class that reaches one of these
  through project base classes is now seeded too: a type table built from the
  scanned `.java` and `.kt` files follows the parsed ancestor chain up to four
  hops, takes the ancestor's kind and seed, and leaves unresolvable and
  colliding bases to the deterministic path rule. On Signal-Android this
  recovers 226 UI, 16 background, and 4 `Application` seed files the
  exact-name rule missed.
- `call_path` starts at the highest-seed entrypoint that reaches a file, not
  whichever root a BFS touched first. The multi-source search runs seed 5
  before 4 before 3; inside one seed the shortest path wins. A UI file whose
  call path used to begin at a service now begins at the UI entrypoint.
- Short constructors named after their class are excluded from candidate
  sites. A constructor is kept only when it spans more than five lines, so
  field assignment such as `MismatchedDevicesException.<init>` is no longer a
  judged site while a constructor with real validation stays.
- Coverage counts judgments, not findings. Phase 2 now writes
  `out/judgments.jsonl`, one `site_id` and finding count per judged site, so a
  judged-and-clean site counts as judged. `rank` unions that file with
  `failure-modes.jsonl`, caps `sites_judged` at `sites_total`, ignores
  impossible ids with a warning, and warns when the file is missing. README
  documents the artifact and its exposure.
- The unsupported-language line on the board counts files per language instead
  of reusing `scanned_files`. On Signal-Android it said “cpp, c (9,982 files)”
  when the scan had seen two such files.
- Plain Rx `.subscribe(` is no longer a consumer entrypoint. On Signal-Android
  it produced 86 of the 113 consumer seeds, all internal subscriptions, so
  reach rested on a false root. The remaining signal requires a
  `worker`/`service` path and `Schedulers.io` on the same line. The other 27
  seeds were Compose `consume()` calls; `consume(` is unchanged by request and
  is documented as a remaining false-seed source on Android.

## 0.3.0

- `context` fills its site cap with a seeded random sample by default
  (`--sample-order random`, `--seed N`). The old reach → inbound → body size
  order is kept as `--sample-order ranked`, unchanged.
- The change follows a measurement, not a preference: on Signal-Android at
  5,000 sites per arm the ranked order and a seeded random sample were
  indistinguishable on rule findings (file-density ratio 0.98, 95% CI
  −0.0057..+0.0049). `references/entrypoints.md` now records that result in
  place of the claim that the order predicts value.
- `context` prints the sampling method and writes `out/sample.json`
  (`mode`, `seed`, `population`, `kept`, `per_file`). `context.jsonl` keeps its
  record-only shape. `report` repeats the method under "Could not determine".
- `sampling` warns when `candidates.jsonl` starts with a shuffled sample, so a
  random population is not mistaken for the ranked comparison.

## 0.2.1

- Test code is excluded from candidate sites, import edges and entrypoints:
  `androidTest/`, `test/`, `*Test`, `*Tests`, `*IT`, `*Spec`, Python `test_*`,
  and `.test`/`.spec` files. On Signal-Android the first candidate sites were
  test helpers; they are now production classes.
- `report --open` renders and opens the HTML board; the skill requires ending a
  run with the board open.

## 0.2.0

- Java and Kotlin are supported languages: the gate counts their lines, imports
  resolve across Maven/Gradle layouts, and methods, `fun`s and class bodies
  become candidate sites.
- Entrypoints: `public static void main`, `fun main`, Spring and JAX-RS
  annotations.
- Same-package Java edges require the peer type name to appear in the importing
  file; visibility alone does not lift a whole package.
- **No JVM defect rules yet.** On a Java or Kotlin repo `detect` returns zero
  findings, so a report covers reachability and phase-2 judgment only.
- README states the supported languages and that limit.

## 0.1.1

- README rewritten for a first-time reader: usage before explanation, the four
  verdicts as a table, badges, and the first-person note on why the tool exists.
- The changelog no longer opens with an empty `Unreleased` heading.

## 0.1.0

First release.

- Scan: `gate` refuses a repo where a ranking would be invented; `context` emits one record per function reachable from an entrypoint; `detect` runs 22 rules, secrets included; `validate` enforces verbatim evidence, site correspondence, prompt hash and confidence cap.
- Rank: impact `blast × silence / 3` discounted to a quarter at reach 1; effort derived from files, call sites, boundary crossings and test presence; noisy-OR clusters; coverage counted; stale rankings refused.
- Report: one self-contained HTML file plus JSON. Shape, curve with an impact-for-effort ladder (50/70/80%), quadrant, top five, verification, batch plan, all findings, could-not-determine. Secrets redacted before publication.
- Verify: probes in a git worktree or a copy; `reproduced` for a defect, `fixed` only on red-to-green with `--fix`; `--scaffold` writes templates and refuses unfilled ones.
- Calibrate: deterministic stratified sample, precision per taxonomy, `incomplete` under 20 filled rows.
- Known limits: reachability is file-level; JS/TS bounds are regex-based; redaction is pattern-based; the skill has not audited a real repository yet, and phase-2 precision is unmeasured until `calibrate` is filled in.
