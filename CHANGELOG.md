# Changelog

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
