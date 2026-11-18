# Entrypoints and reachability

`reach` decides whether a finding matters. Everything here is heuristic — treat it as evidence, not proof.

## Extraction targets

| Kind | How it is found | seed |
|---|---|---|
| HTTP route | framework-specific patterns below, including Django `include(`, Spring `@GetMapping`, JAX-RS `@GET` | 5 |
| Android UI | a class extending `Activity`, `AppCompatActivity`, `ComponentActivity`, `FragmentActivity`, or `Fragment`, directly or through a project base (up to four hops) | 5 |
| iOS UI | `@main`, `@UIApplicationMain`, or `UIApplicationMain(`; a `UIViewController` or `UIView` subclass, directly or through a project base (up to four hops); ObjC `@interface X : UIViewController` | 5 |
| Middleware | `app.use('<path>', …)` — on the request path, not a route | 4 |
| Android background | a class extending `Service`, `IntentService`, `JobService`, `Worker`, `BroadcastReceiver`, or `ContentProvider`, directly or through a project base | 4 |
| Queue consumer | `.consume(` only when the receiver or the line names a queue, plus `new Consumer(`, `@app.task`, `@shared_task`, and the narrow Rx signal below | 4 |
| Cron / scheduled | `cron.schedule`, `setInterval`, `@scheduled`, `schedule.every` | 4 |
| CLI command | `package.json` `bin`, `#!/usr/bin/env node`, `if __name__ == "__main__"`, argparse/click/typer, `public static void main(`, `fun main(` | 3 |
| iOS application | a class conforming to `UIApplicationDelegate`, `AppDelegate`, or `SceneDelegate`; ObjC `@interface X : NSObject <UIApplicationDelegate>` | 3 |
| Android application | a class extending `Application`, directly or through a project base | 3 |
| Public API | an `export` or `__all__` in `index.{ts,js}`, `index.tsx`, or `__init__.py` | 3 |

A file that is several things gets the best seed. Each import hop costs one level, down to a floor of 2.

## The entrypoint language has to carry the repo

An entrypoint counts only when its language holds at least **5% of the supported non-blank lines**. Below that, the entrypoints are ignored and the gate names the language in a warning; if nothing survives, the gate refuses rather than deriving reachability from a helper language.

The measurement is per repo and applies to every repo. Signal-iOS is the case that motivated it: 22 bundled Python files supplied 39 CLI entrypoints beside 705k lines of Swift that supplied none, so the gate passed on tooling while saying nothing about the app.

An entrypoint on a file with no source language — a `package.json` `bin`, which names a script rather than holding one — is not judged by share: it has no lines of its own to weigh. `scope.json` records the kept entrypoints in `entrypoints`, the ignored languages in `entrypoints_ignored`, and the floor in `gate.entrypoint_language_floor`.


## Framework patterns (v1)

```
Express      app.(get|post|put|patch|delete|use)  ·  router.(get|post|…)
Fastify      fastify.(get|post|…)  ·  fastify.route({
Next.js      files under pages/api/**  ·  app/**/route.{ts,js} exporting GET/POST
FastAPI      @app.(get|post|…)  ·  @router.(get|post|…)
Flask        @app.route  ·  @bp.route  ·  Blueprint.add_url_rule
Django       urls.py entries: path( · re_path( · include(
Spring       @GetMapping · @PostMapping · @RequestMapping (verb from method=) · @Put/@Delete/@PatchMapping
JAX-RS       @GET · @POST — the path lives in a separate @Path and is not joined
Android      Java `extends` / Kotlin `:` against a component base name:
             Activity · AppCompatActivity · ComponentActivity · FragmentActivity · Fragment
             Service · IntentService · JobService · Worker · BroadcastReceiver · ContentProvider
             Application
```

Adding a framework is one regex family plus one fixture. Do not add a framework without a fixture that proves the extraction works.

A `@RequestMapping` with no `method=` is seeded as `ANY <path>`; a JAX-RS detail carries the verb and no path, because guessing the class-level `@Path` would be invention. Annotations in comments are not special-cased.

### Android components

The framework instantiates Activities, Services, receivers, providers, Workers, and the `Application` itself; nothing in the codebase calls them, so a file that holds one is an entrypoint by declaration. Details name the component: `ACTIVITY FeedActivity`, `SERVICE SyncService`, `WORKER UploadWorker`, `RECEIVER BootReceiver`, `PROVIDER NotesProvider`, `APPLICATION AcmeApp`. A `Worker` is labelled `WORKER`, not `SERVICE`: calling it a service would put a class on the board that does not exist. Both `extends` and `implements` are read in Java, and the Kotlin supertype list after the first top-level `:` is read, so a wrapped constructor header still resolves. A type that appears only in a constructor parameter or a body comment is not a base.

Only these exact base names match directly. A class that reaches one through a project base is also seeded: the extractor builds a type table from the scanned `.java` and `.kt` files (`declaration name -> file`), reads each class's supertypes, and walks the ancestor chain up to four hops. `class ConversationActivity : PassphraseRequiredActivity()`, where `PassphraseRequiredActivity` extends `BaseActivity` and that extends `AppCompatActivity`, is a `ui` seed at seed 5. The kind and seed come from the component at the end of the parsed chain; the detail still names the class that is the entrypoint (`ACTIVITY ConversationActivity`). A name declared in more than one scanned file resolves to the declaration with the fewest path segments, then the lexicographically first path.

An ancestor that is neither a component base nor a declaration in the scanned set is a dead branch: the class is **not** seeded. The extractor never guesses a base from its name, so a dependency class outside the repo, a generated base with no scanned source, and a typo all stay unseeded rather than inventing a root. A class named `Activity` in some other framework is indistinguishable and would be seeded: base names are checked, not imports.

Measured on Signal-Android (9,982 files, 819,290 non-blank lines): before following project bases the scan finds 73 `ui`, 53 `background` (38 receivers, 14 services, one provider), and 6 `app`. With the four-hop chain it finds 299 `ui`, 69 `background` (46 receivers, 19 services, four providers), and 10 `app` — 246 more components, which matches the ~248 counted by hand. `ComposeFragment` alone accounts for 95 UI classes. The seed count is still a floor — a base class declared outside the scanned set, or a chain longer than four hops, stays out — and the report says so.

## Removed: plain `.subscribe(`

`.subscribe(` used to be a consumer entrypoint. On Signal-Android it produced 86 of the 113 “consumer” seeds, and all 86 were internal RxJava subscriptions inside the app — UI streams, database observers, in-process buses. None of them is a queue. Every reach number behind those seeds was resting on a false entrypoint.

The pattern is removed. `new Consumer(`, `@app.task`, and `@shared_task` remain.

## Narrowed: `.consume(`

`.consume(` alone is not a queue signal. On Signal-Android the other 27 consumer seeds were Compose pointer `consume()` calls in gesture code, which clear a pointer event and do no work. The call counts only when one of these is true:

1. the receiver identifier matches `consumer`, `queue`, or `subscription` (case-insensitive) — `kafkaConsumer.consume(`, `queue.consume(`;
2. the line contains `topic`, `queueName`, or `partition`.

`it.consume()` in a gesture handler, and `channel.consume('jobs', handle)` with a bare receiver, are not seeds. The cost is real: AMQP code that consumes through a `channel`, or through a plain `basicConsume` call, loses its seed unless the line names the topic or queue. That is the price of dropping 27 false seeds on Android, and it belongs in the report as a known miss rather than a clean result.

Measured on Signal-Android: the 27 consumer seeds drop to 0. Fifteen files call `.consume(` there, and none names a topic, `queueName`, or partition on the line. `new Consumer(`, `@app.task`, and `@shared_task` do not occur, so the consumer kind disappears from that repo's counts.

A narrow Rx replacement exists because an Rx subscription to I/O can be a real workload boundary. It counts only when both are true:

1. the file path contains `worker` or `service` (case-insensitive), and
2. the line with `subscribe(` also contains `Schedulers.io`.

Anything less specific is not a seed. A false seed is worse than a missing one: it lifts every finding the call graph reaches, and the report has no way to discount a reach that was invented at the root. If in doubt, leave it out and say so under “Could not determine”.

## Call graph and reach

```
reach = 5  the file registers a route, is an Android UI component, or is included
reach = 4  middleware, cron, consumer, or Android background component
reach = 3  CLI entrypoint, package export, or Android Application subclass
reach = 2  imported within depth 3 of any seed, floor
reach = 1  present in the repo, no path from any entrypoint
reach = 0  in the repo but unreadable (binary, oversized, non-utf-8)
```

`reach == 0` never attaches to a finding: an unreadable file cannot produce one, and `rank` drops any finding that claims 0. `reach == 1` multiplies impact by 0.25 — dead-code findings are ranked, not discarded, because static reachability is a heuristic.

Path search is static, following imports only. It does not follow dynamic dispatch, dependency injection, reflection, event buses, or string-based routing.

## Resolution

A specifier resolves in this order: a relative path (`./x`, `../y`); a `paths` alias from `tsconfig.json` (`@app/*` → `src/*`) relative to `baseUrl`; a workspace package name from `package.json` `workspaces` (`@acme/lib`); otherwise nothing. An unresolved bare import — `express`, `react` — is dropped, not guessed.

Java and Kotlin resolve dotted imports against the scanned files. The source root (`src/main/java`, `src/main/kotlin`, `app/src/main/java`) is never named by the import, so `com.acme.Foo` matches any scanned path ending in `com/acme/Foo.java`; two roots providing the same suffix resolve to the shallower path, then the lexicographically first. `import com.acme.Foo` in Kotlin tries `Foo.kt`, `foo.kt`, then `Foo.java`, because a lowercase file can hold a top-level declaration imported by name and mixed projects exist. Wildcard and star imports name no file and add no edge. A Java `import static a.b.C.member` resolves to `C.java` by trimming trailing segments. Java classes in the same directory are the same package, so a peer is an edge only when its type name appears in the importing file; visibility alone would lift every class in a large package. Kotlin has the same implicit package visibility and it is not modelled. A `package` declaration that disagrees with the directory, and every external jar and JDK import, stays unresolved.

Objective-C `#import "A/B.h"` and `#import <A/B.h>` resolve against the scanned files the same way: the header search path the import assumes is never named, so any scanned path ending in `A/B.h` matches, a bare `"B.h"` matches by basename, and ties pick the shallower path then the lexicographically first. An import that starts with `.` is normalised from the importing file's directory first. A header and its implementation are one logical file: an edge that lands on `X.h` is recorded against `X.m` or `X.mm`, so the two files are not counted separately and an implementation importing its own header adds no edge. Headers are import targets, not code: they are never graph nodes and their lines are never counted as supported code. A header with no implementation, and every `#import <Foundation/Foundation.h>`-style system import, resolves to nothing.

Swift has no file-level imports. A Swift file can call anything in its module, so the module — the Xcode target — is what connects two files. `project.pbxproj` is read from every `*.xcodeproj` in the tree for target membership (`PBXSourcesBuildPhase` → `PBXBuildFile` → `PBXFileReference`, with paths rebuilt through the group tree), and matched to scanned paths by trailing segments. Two Swift files are neighbours only when they are in the same target **and** the importing file names a type the other file declares (`class`, `struct`, `enum`, `protocol`, `actor`, `typealias`); comments are stripped before both steps, so a commented-out declaration or mention counts for neither. `import Foo` names a module: when `Foo` is another target's product it adds an edge to that target's files, and otherwise it is ignored. With no project file there are no intra-target edges, and the run says so in its mode line instead of guessing.

Broken or absent manifests leave the alias set empty, and resolution falls back to relative paths alone. That is degradation, not failure.

Depth defaults to 3 and is settable per run: `context --max-depth N` and `detect --max-depth N`, 1–10. Raise it when a repo routes through many thin re-export modules; lower it when a hub makes everything look reachable.

## Known blind spots — state these in the report

- Dependency injection and dynamic `require`/`import` are invisible. A function that looks dead may be wired by a container.
- Event emitters and message brokers break the graph into disconnected islands.
- Monorepos with path aliases fail import resolution unless the alias map is read.
- Generated code and codegen stubs inflate or distort the graph.
- Test-only reachability (1) is a strong demotion, not proof of dead code — a package can be consumed by another repo.

## Degraded mode

If the call graph fails to resolve (no tree-sitter grammar, alias soup), fall back to **file-level reachability**: a finding scores 5 if its file is imported, directly or transitively, by a route module; 3 if exported from a package entry; 1 otherwise.

When degrading, the report must say so in one line, and every affected finding is capped at `confidence: med`. Silent degradation is the worst outcome available to this tool.

## Candidate sites for phase 2

`pareto-triage context` turns reachability into the input phase 2 needs: one record per function whose file scores `reach >= 2`. Files at `reach = 1` are excluded — judging functions nothing reaches is how a report fills up with findings that cannot matter.

| Field | Meaning |
|---|---|
| `site_id` | `s_001…`, assigned in output order, stable for the same tree |
| `file`, `lines` | the function's bounds, 1-based, inclusive |
| `function` | symbol name; Python uses `Class.method`, inline handlers use the route, e.g. `POST /webhooks/stripe` |
| `lang` | `ts`, `js`, `py`, `java`, or `kotlin` |
| `reach` | file-level, from the graph above |
| `call_path` | entrypoint detail, then each file on the best import path, then the function. File-level, not symbol-level — it says which files carry the call, not which functions call which. The path starts at the highest-seed entrypoint that reaches the file (5 before 4 before 3); among paths from that seed, the shortest wins, ties break deterministically |
| `source` | verbatim lines, capped by `--max-lines` |
| `surrounding` | the file's imports, client construction (`new Client(…)`, `axios.create(…)`), and middleware registration (`app.use(…)`), in file order, quoted as-is, capped at 60 lines. `surrounding_truncated` says when the cap was hit |
| `truncated` | true when the body exceeded the cap. A finding quoting past the cut will fail `validate`, which is the intended signal |

Python bounds come from `ast`. TypeScript and JavaScript bounds come from regex headers plus brace matching that skips strings, template literals, and comments. That is approximate: a mis-parsed arrow function produces a body that fails the evidence check rather than a plausible-looking wrong site.

Java and Kotlin use the same brace matching. A method or `fun` site starts at the declaration, or at contiguous annotation lines directly above it, and ends at its closing brace. Java needs a brace after any `throws` clause; Kotlin accepts `=` as an expression body, whose bounds are its line plus any still-open brackets. A class body is a site only when it contains no method already emitted — the nested-site rule below does that. Interface members with no body, and records, are not sites. What breaks it: braces inside a Java text block or a Kotlin raw string are skipped as strings, but code inside a `${…}` template is not parsed; an expression body wrapped without brackets ends at its first newline; annotation arguments that wrap to following lines start the site below the `@`.

Overlapping sites are collapsed: when a function is defined inside another, only the inner one is emitted, with `enclosed_by` naming its container. Judging a handler and the closure inside it as two sites would score the same lines twice. `context --include-enclosing` keeps both for anyone who wants the old view.

Default cap is 400 sites, filled by a seeded shuffle of the candidate population (`--sample-order random`, the default), with the per-file cap applied after the shuffle. `--seed N` (default 0) makes the draw reproducible; the same tree, seed, and limit produce the same `context.jsonl`. `--sample-order ranked` restores the reach → inbound → body size → path order. The cap is reported; it is never silent. Raise it with `--limit` when a large repo needs a second pass.

Random is the default because the ranked order was measured and did not beat it — see the next section. `context` prints the method:

```
sample     random, seed 0: kept 400 of 5,412 candidates, max 20 per file
           rule findings cover every file; this is a sample only for judgment
```

It also writes `out/sample.json` with `{mode, seed, population, kept, per_file}`. `context.jsonl` stays record-only: the sampling method lives in that sidecar, and `report` repeats it under "Could not determine".

## Is the selection better than random?

Measured on Signal-Android with 5,000 sites per arm, the ranked selection and a seeded random sample of the same size were **indistinguishable** on rule findings: `file_density` ratio 0.98, 95% CI on the difference −0.0057..+0.0049. The interval is tight around zero, so any edge on this measurement is smaller than half a percentage point of file density. That does not justify a default, and it is not proof that no ordering can help on any repo. So `random` is the default and `ranked` stays behind a flag — as the thing that was measured, not as a recommendation.

The comparison stays reproducible. `context --all` writes `out/candidates.jsonl` — every candidate, not just the first 400 — so any ordering can be tested without a model in the loop. Write the population with `--sample-order ranked` when the point is to re-test the ranked order: the selected set is the prefix of `candidates.jsonl`, so a population written with the default shuffle makes `sampling` compare random against random. `sampling` warns when `sample.json` says the population was shuffled.

The file has the same record shape as `context.jsonl`. Its order is the contract: the selected sites come first, exactly as `context.jsonl` emitted them (in the run's sampling order, with the per-file cap and `--limit` applied), and every other candidate follows in the ranked order. `site_id` is assigned over that whole order, so the first N records are the selected set. `--save-candidates PATH` writes the same file somewhere else.

### What the sample covers

`detect` runs on every file. A rule finding outside the sampled sites is still emitted, scored, and ranked; the sample never narrows the mechanical pass.

The sample bounds phase-2 judgment only. The model judges the functions in `context.jsonl`, so a failure mode — a missing timeout, a swallowed error — in a function outside the sample is not assessed at all. The report counts those sites as unjudged, not as clean. The sample also says nothing about severity, impact, or what to fix first; those come from the ranking, which covers findings from the whole tree.

`pareto-triage sampling <repo> [--limit N] [--seed N]` reads `out/candidates.jsonl`, `out/defects.jsonl`, and `out/failure-modes.jsonl` when present. It takes the first N records — N is `--limit`, default 400, capped at the population — as the selected set, and draws a seeded random sample of the same size from the whole population. For each set it measures:

| Share | A site counts when |
|---|---|
| `file_density` | its file contains at least one rule finding |
| `line_density` | a rule finding's line falls inside its `lines` range |

`out/sampling.json` records the population, N, the seed, both shares for both sets, the ratio, the difference, and a 95% interval on the difference (normal approximation). It also records the site ids of both samples, so the draw can be audited. The verdict comes from `file_density`: **ordering beats random** when the interval is entirely above zero, **indistinguishable** when it straddles zero, and **ordering is worse than random** when it is entirely below. `line_density` carries its own verdict in the same file.

The measurement is mechanical only. Phase-2 failure modes are loaded and counted as `failure_modes_ignored`, but never included in either density: a model judgment is not a mechanical finding. A missing finding is not proof that a site is clean — the rules only prove what they can see at a line. Read a flat result as "this ordering has not demonstrated an edge over random on rule findings", not as "no ordering can work". Re-run with several seeds before believing a small difference. Pass the same `--limit` to `context --all` and `sampling`; the prefix is only exactly `context.jsonl` when the two agree.

To falsify the ordering:

```sh
S=scripts/pareto-triage.py
python3 $S gate <repo>
python3 $S context <repo> --all --sample-order ranked
python3 $S detect <repo>
python3 $S sampling <repo> --seed 0
```

If the interval straddles zero, the claim that the selected sites carry more rule findings than random ones is unsupported on that repo. That is a real answer, and it belongs in the report. It is the answer measured on Signal-Android, and the reason `random` is the default.

