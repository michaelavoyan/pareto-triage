# Defect rules

The tool-verifiable tier. A rule goes in here only if its **presence** at a line is certain. Whether it matters is the rubric's job, not the rule's.

No external scanners are required. Semgrep, CodeQL, tsc, and eslint are stronger tools, but they are also installs, versions, and failures. v1 ships a narrow rule set that always works offline, plus the same finding schema so an external scanner can be added later as an adapter without touching the pipeline.

Swift and Objective-C are not in this file because there are no rules for them. `detect` reports rule coverage per language (`0/9 files (no rules)`) and warns when a supported language had files but no detector; `rank` records that in `could_not_determine`. An empty `detect` result in those languages is unassessed code, not clean code.

## Rules

The tables below list all 28 active rules.

### Python (AST-based, `ast.parse`)

| Rule | Taxonomy | Blast | Silence | Catches |
|---|---|---|---|---|
| `py-eval` | code-injection | 5 | 2 | `eval(...)`, `exec(...)` |
| `py-os-system` | command-injection | 5 | 2 | `os.system(...)` |
| `py-shell-true` | command-injection | 5 | 2 | any call with `shell=True` |
| `py-pickle` | unsafe-deserialization | 5 | 3 | `pickle/cPickle/dill.load[s]` |
| `py-yaml-load` | unsafe-deserialization | 5 | 3 | `yaml.load(...)` with no safe `Loader` |
| `py-sql-interp` | sql-injection | 5 | 2 | `.execute`/`.executemany` with f-string, `%`, or `.format` |
| `py-verify-false` | tls-verification-disabled | 5 | 3 | `verify=False` |
| `py-bare-except` | bare-except | 4 | 3 | `except:` with no type |
| `py-mutable-default` | mutable-default-arg | 3 | 3 | list/dict/set literal as a default |
| `py-debug-true` | debug-mode-enabled | 4 | 2 | `debug=True` in a call |

### JavaScript / TypeScript (regex, comment lines skipped)

| Rule | Taxonomy | Blast | Silence | Catches |
|---|---|---|---|---|
| `js-eval` | code-injection | 5 | 2 | `eval(` |
| `js-new-function` | code-injection | 5 | 2 | `new Function(` |
| `js-exec-interp` | command-injection | 5 | 2 | `exec`/`execSync` on a template with `${`, in a file that imports `child_process` |
| `js-tls-off` | tls-verification-disabled | 5 | 3 | `rejectUnauthorized: false` |
| `js-secret-aws` | hardcoded-secret | 5 | 3 | `AKIA…` key |
| `js-secret-pem` | hardcoded-secret | 5 | 3 | `BEGIN … PRIVATE KEY` |
| `js-secret-stripe` | hardcoded-secret | 5 | 3 | `sk_live_…` |
| `js-dangerous-html` | xss | 5 | 1 | `dangerouslySetInnerHTML` |
| `js-unvalidated-input` | missing-boundary-validation | 3 | 3 | `req.body.X`, `req.query.X`, or `req.params.X` reaching `query`/`execute`/`prepare`/`run` or a shell call in a route file |

`exec(` is not a shell call by itself: `db.exec(...)` on a SQLite handle, a query runner, and a process pool all use the name. `js-exec-interp` requires the file to import `child_process` (`import … from 'child_process'`, `require('child_process')`, or the `node:` form) and the call to be `exec` or `execSync`. `execFile` and `execFileSync` take a program and an argument vector and reach a shell only when the same line passes `shell: true`, so only that shape fires; an interpolated argument without the option is silent. `spawn` and `spawnSync` are not matched for the same reason: without `shell: true` an interpolated argument is one element of an argument vector, not a shell string. The cost is a false negative for `spawn(..., { shell: true })` and for `execFile` with the option on a later line. Both are recorded here rather than guessed at from a line that does not show the shell.

`js-unvalidated-input` is the only JS rule that reads past one line. It requires a route registration (`app`/`router`/`server`/`fastify` plus a verb) in the file, then follows a value from `req.body.X`, `req.query.X`, or `req.params.X` — directly or through one assignment — to a DB method (`query`, `execute`, `prepare`, `run`) or, in a file importing `child_process`, a shell call. A validator import or call before the sink (`zod`, `joi`, `yup`, `express-validator`, `celebrate`) silences the file, and `Number(...)`, `parseInt(...)`, or `JSON.parse(...)` on the same statement counts as the parse for that scalar. It is one hop, not dataflow: a value copied through a second function is missed, and a validator that runs after the sink does not silence it.

### Java / Kotlin (regex, comment lines skipped)

| Rule | Taxonomy | Blast | Silence | Catches |
|---|---|---|---|---|
| `jvm-exec-injection` | command-injection | 5 | 2 | `Runtime.getRuntime().exec(` or `ProcessBuilder(` with `+` on the same line, where a `+` operand is not a compile-time constant |
| `jvm-sql-injection` | sql-injection | 5 | 2 | `executeQuery`/`executeUpdate`/`execute` with `+` on the same line and a statement verb (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `REPLACE INTO`) inside the call |
| `jvm-weak-hash` | weak-hash | 3 | 3 | `MessageDigest.getInstance("MD5")` or `"SHA-1"` |
| `jvm-object-input-stream` | unsafe-deserialization | 5 | 3 | `new ObjectInputStream(` |
| `jvm-write-without-transaction` | non-atomic-write | 3 | 2 | two DB writes (`insert`/`update`/`delete`/`replace`/`upsert`/`execSQL`) in one method with no transaction call |

The JVM rules are line-local by design: a `+`, a quote, an algorithm name, or a constructor call is either there or it is not. `jvm-weak-hash` proves the algorithm at the line, never its role: an MD5 used only to bucket a value — a cache key, a dictionary key, a display-name collision digest — fires the same as an MD5 guarding a signature. Detection is certain, severity is contextual, so blast is 3 rather than 5. The `WeakHashBucketing` fixture is that shape and is expected to fire.

Line-local precision needs one more test each. `execute(` is a name shared by SQL statements, executors, and callback dispatchers, so `jvm-sql-injection` also requires a statement verb inside the call's parentheses: `keyedExecutor.execute("Call::" + id, …)` is quiet, `stmt.execute("DELETE FROM t WHERE id = " + id)` is not. `jvm-exec-injection` requires at least one `+` operand that is not a compile-time constant: a lowercase name, a field, a parameter, an array element, or a call is a value; `UPPER_SNAKE_CASE` names (`FILTER_SPEC`, `BuildConfig.ENDPOINT`), quoted literals, and numeric literals are constants. `exec("logcat -d " + FILTER_SPEC)` is a fixed command, not injection; `exec("convert " + path)` is. Both rules ignore calls inside comments and string literals.

`jvm-write-without-transaction` reads method bodies with the same brace matcher `context` uses. It counts a write only when the receiver names a database (`db`, `database`, `writableDatabase`, `readableDatabase`, `SignalDatabase…`, a `…Database`/`…Dao` receiver, or a content resolver), so `Cipher.update` and `MessageDigest.update` do not count, and `execSQL` needs no receiver. Two writes with no `beginTransaction`, `inTransaction`, `withTransaction`, or `endTransaction` in the body fire once, at the first write. The rule cannot see a transaction opened by the caller, a `withinTransaction` extension, or the framework transaction around `onCreate`/`onUpgrade`; those limits are why its measured precision is recorded under "Considered and rejected".

## Effort for a rule match

A rule match is mechanical, local work with no design decision, so it uses the reduced formula in `references/rubric.md`: `1 + no_test + boundary`, clamped to 1–5. `rank` computes it; the drivers are recorded on the finding. Effort stays ordinal: the ranking needs "cheaper than", never hours.

## Evidence

Evidence is the source segment of the matched node (Python) or the matched source line (`js` and JVM), whitespace-trimmed. It is copied, never reconstructed, so `pareto-triage validate` passes by construction and the hallucination guard stays meaningful for agent findings.

## Precision contract

A rule that fires on code the maintainer would call correct is a bug in the rule. When that happens, narrow the rule or delete it — do not add a suppression flag. The defect tier is the part of the report nobody can argue with, and one false "critical" spends that credibility permanently.

Known false-positive sources, accepted for v1:

- the tool scanning its own rule tables (regex literals inside a scanner are matches)
- test fixtures that deliberately contain vulnerable patterns
- generated code and vendored snippets below the ignore list
- a trailing comment on a JVM code line, or an unrelated `+` on the same line as a JVM call, because the JVM rules are line-local and skip only lines that begin with `//`, `*`, or `/*`

These are visible in the report's "could not determine" section via file counts.

## Adding a rule

1. Add the meta entry in `scripts/lib/rules.py`.
2. Add a fixture line that triggers it and a line that must not.
3. Add a test asserting exactly which rules fire on the fixture.
4. Add the row to this table.

A rule without a negative fixture is a guess.

## Rule-count guard

`scripts/check_rule_counts.py` runs `gate` and `detect` on `fixtures/jvm-rules`
and `fixtures/express-app`, reads `rule_incidence` from each `scope.json`, and
compares it with `scripts/test/golden/rule-incidence.json`. A rule that stops
firing, or that stops running because a language branch was dropped, fails CI.
The guard is dependency-free and runs the real CLI, so it tests the shipped
pipeline rather than a helper. After an intended count change, run
`python3 scripts/check_rule_counts.py --write` and explain the new counts in
the commit. A golden update with no explanation is how a silent zero gets
merged.

## Secrets outside source files

Secrets are matched in `.env`, YAML, JSON, Terraform, TOML, INI, `.properties`, and `.conf` as well as source, because that is where they usually are. Source means `.py`, JavaScript/TypeScript, and `.java`/`.kt`/`.kts`, which reuse the same three patterns under the same rule ids. Only the secret rules run on the non-source files; code rules are meaningless there.

A secret finding means a **committed** secret. When the scanned tree is inside a git work tree and `git` is available, the config-secret rules read only the paths `git ls-files` reports as tracked. An untracked, gitignored `.env` is not part of the repository, so reporting its contents as a committed secret is a false positive at blast 4; `detect` prints `secrets    git-tracked config files only, N untracked skipped`. Source-file secret rules are not narrowed: a key hardcoded in a `.py` file is a finding whether or not that file has been committed, because the source is what gets published.

When the commit set cannot be established — git is not installed, the tree is not a repository, or `git ls-files` fails — the wider behaviour stands and `scope.json` records why:

```json
"secrets": {"tracked_only": false, "reason": "not inside a git work tree: commit status is unknown, so every config file is scanned"}
```

With a work tree the entry is `"tracked_only": true` and the reason names `git ls-files`. The field is written by `gate`, so the scope a scan used is inspectable after the fact; `detect` re-checks it and warns if the commit set changed.

| Rule | Where | Matches |
|---|---|---|
| `py-secret-aws` | any scanned file | `AKIA` + 16 characters |
| `py-secret-pem` | any scanned file | a private-key block header |
| `py-secret-stripe` | any scanned file | `sk_live_` + 10 |
| `cfg-secret-generic` | tracked config files | a credential key assigned a literal value |

The generic rule ignores values that are code references: `process.env.TOKEN`, `os.environ[...]`, and `${VAR}` are not secrets, and masking them would make the evidence say something false.

## Redaction

A finding's `evidence` is quoted verbatim, which means a found secret is a published secret. `report` redacts evidence in `report.json` and `report.html` and lists every redaction in "Could not determine". `out/defects.jsonl` keeps the raw line — the evidence guard needs it — so that file must not be committed or shared. It is not part of the published artifact set.

## Considered and rejected

Rules that were implemented, measured, and withdrawn. Recorded so the measurement survives and nobody re-proposes them without new evidence.

### `jvm-sql-template` — rejected, 0/12 precision

A Kotlin string template (`"SELECT … WHERE id = $id"`) passed to `query`, `raw`, `executeQuery`, `executeUpdate`, `execute`, or `exec`, with the existing statement-verb requirement. The candidate was a branch of `jvm-sql-injection`, not a new rule id.

On Signal-Android at `2dd5703` it produced 12 findings across 8,906 non-test Java/Kotlin files. All 12 were `DELIBERATE`: every interpolation was an identifier — a table or column name, or a compile-time constant — which SQL cannot bind with `?`. None carried a value that could be a bound parameter. True positives 0, false negatives none observed, precision 0.00.

| Where | Interpolated |
|---|---|
| `app/.../InternalSettingsFragment.kt:1412` | `${OneTimePreKeyTable.TABLE_NAME}` |
| `app/.../ContactIndexDatabase.kt:303` | `${ROW_COLUMNS…}`, `$TABLE_NAME`, `$ID` (values are `?` + `arrayOf`) |
| `app/.../AttachmentTable.kt:4172`, `:4200` | `$DATA_HASH_END`, `$REMOTE_KEY`, `$TABLE_NAME`, `$QUOTE`, … |
| `app/.../V172_GroupMembershipMigration.kt:38` | `${index * 500}` (internal loop counter) |
| `core/.../SQLiteDatabaseExtensions.kt:64`, `:610`, `:623` | `$table`, `$tableName` (callers pass constants) |
| `core/.../SqlUtil.kt:78`, `:83`, `:135` | `$table` |
| `lib/spinner/.../DatabaseUtil.kt:30` | `$table` |

Withdrawn: a Kotlin template is the same syntax for a value and for an identifier, and the line does not say which. The corpus answer was every identifier and no values, so the branch would have spent the defect tier's credibility on code the maintainers wrote correctly. Narrowing it to comparison positions (`= $x`, `IN ($x)`) would have produced zero hits on both corpora: unmeasured, not precise. The firing shape stays in `fixtures/jvm-rules/src/main/kotlin/com/acme/SqlTemplate.kt` and is asserted silent.

### `jvm-empty-catch` — rejected, 0/60 precision

Fires on a `catch` block whose body is empty or comments only.

An audit of all 60 findings on Signal-Android at `8959dc6` found no true positives. 55 were deliberate: cleanup, optional work, or parse/validation control flow where the failure has no recoverable meaning and the catch is the handling. 5 were mechanically false, all from one cause — a catch whose body is a string literal, which the literal masking turned into whitespace: `NameCollisionTables.kt:489` (`""`), `LogSectionSystemInfo.kt:103` (`"Unknown"`), `RingRtcDynamicConfiguration.kt:115` and `:131` (`""`), and `debuglogs-viewer/WebView.kt:88` (a template). Those five are now fixtures.

Withdrawn: whether a catch may swallow is intent, and intent is not line-local. `taxonomy.md` already names the optional-operation counter-example, and the 55 deliberate findings are that shape: the same code is correct when the caller's contract allows partial success. Deciding it needs the caller and the contract, not the line, so the rule cannot reach a precision the defect tier can defend. The masking helper was fixed in the same release: a string literal counts as a body, a comment does not.

### `jvm-http-no-timeout` — rejected, 0/4 precision

Fires on a client builder chain with no timeout call. On Signal-Android it produced four findings and none were defects: OkHttp applies 10 s connect/read/write defaults, and `taxonomy.md` says a library default is not a finding. One case (`SignalRestClient.kt:117`) clones the base client and sets both timeouts per call.

Withdrawn: a line-local rule cannot see defaults or a cloned configuration, so it cannot distinguish absence from a default. Implementing it would require following a builder to its use sites — a dataflow change, not a regex.

### `jvm-log-only-catch` — rejected, ~25% precision

Fires on a catch whose body only logs. On Signal-Android it produced 341 findings; an evenly spaced 21-finding sample held about 5 real swallowed failures, the rest being cleanup, optional UI, telemetry, or a logged failure followed by a deliberate `null`/`emptySet()` default.

Withdrawn: whether a catch may swallow is the judgment phase's job, and `taxonomy.md` already names the optional-operation counter-example. A structural rule cannot read intent, and at 25% precision the 341 findings buried the findings that are true — 61 of them on the Signal tree measured for 0.4.3.

### `jvm-trust-all` — rejected, 0 findings, true-positive rate not measurable

Fires when a `checkServerTrusted` or `checkClientTrusted` declaration in a trust manager has an empty body, or a body that only logs, so every chain is accepted. The body is read, not assumed: a throw, a delegation, or any read of the certificates silences it.

On Signal-Android the rule produced no findings across 8,906 non-test Java/Kotlin files (1,130 test files excluded by `detect`). Every trust-manager method in the tree is sound by this rule: `SelfSignedIdentity.ApprovingTrustManager.checkServerTrusted` checks the chain length, `BlacklistingTrustManager.checkServerTrusted` walks the chain and then delegates, its `checkClientTrusted` delegates, and the remaining `checkClientTrusted` throws. Including test code, the only matching shape in the whole tree is `BlacklistingTrustManagerTest.kt:125`, a test double whose `checkClientTrusted` is `= Unit` because the test never uses client certificates; test code is out of scope and that instance is not an application defect. Fixtures and unit tests covered the firing shapes plus throwing, chain-inspecting, delegating, and Kotlin expression-body forms before withdrawal.

Withdrawn: zero findings means zero findings to inspect, so the rule cannot show 70% true positives; 0/0 is not a pass. The rule was precise on what it did not match, but incidence on Signal-Android is zero, and shipping it would claim coverage the corpus never exercised. Re-propose only with a corpus that contains a trust-all manager.

### `jvm-hostname-verifier-true` — rejected, 0 findings, true-positive rate not measurable

Fires when a `HostnameVerifier` implementation's `verify` body is only `return true;`, or a Kotlin lambda is `HostnameVerifier { _, _ -> true }`. A body that delegates or compares hostnames silences it.

On Signal-Android the rule produced no findings across the same 8,906 files. The one `HostnameVerifier` use in app code, `ConscryptSignal.wrapHostnameVerifier`, delegates to `verifier.verify(hostname, session)`. No implementation, anonymous class, or lambda returns an unconditional `true`, in tests included. One Java implementation and one Kotlin lambda fired in the fixture, and delegating and comparing counterparts stayed quiet.

Withdrawn: same arithmetic as `jvm-trust-all`. With no instance to inspect there is no true-positive rate to accept, and an unexercised rule claims coverage it never demonstrated. Re-propose only with a corpus that contains an unconditional verifier.

### `js-sql-template` — rejected, 0 findings, true-positive rate not measurable

Fires on a template literal with `${` passed as the first argument to `query`, `execute`, `exec`, or `raw`, but only when the receiver names a database (`db`, `database`, `pool`, `client`, `conn`, `statement`, `sql`) or the file imports a SQL driver, and only when no values argument follows the template. A parameter array (`query(sql, [ ... ])`), placeholder text with values (`query("… ?", [id])`), a non-database receiver in a file with no driver import, and a bare `query(` are silent. Correct by construction on every shape it was built against: no known false positive, and the two scopes are proved before it fires.

On JobPilot at `37aceae` it produced no findings across 111 non-test files, and on Signal-Android at `2dd5703` no findings across 8,906 non-test Java/Kotlin files. JobPilot's SQL is all `prepare`/`exec` with static text or `?` plus values, and Signal-Android has no TypeScript/JavaScript application SQL.

Withdrawn: zero findings means zero findings to inspect, so the rule cannot show 70% true positives; 0/0 is not a pass. This is the same standard that withdrew `jvm-trust-all` and `jvm-hostname-verifier-true`. A rule that fires on no line of either measured corpus claims coverage the corpus never exercised, and shipping it would hide that gap behind a rule count. The silent shapes stay as `fixtures/express-app/src/sql.ts`, asserted by `scripts/test/test_sql_shapes.py` to produce no finding from any rule. Re-propose only with a corpus that contains SQL assembled from a JS template literal.
