# Defect rules

The tool-verifiable tier. A rule goes in here only if its **presence** at a line is certain. Whether it matters is the rubric's job, not the rule's.

No external scanners are required. Semgrep, CodeQL, tsc, and eslint are stronger tools, but they are also installs, versions, and failures. v1 ships a narrow rule set that always works offline, plus the same finding schema so an external scanner can be added later as an adapter without touching the pipeline.

## Rules

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
| `js-exec-interp` | command-injection | 5 | 2 | `exec`/`spawn` on a template with `${` |
| `js-tls-off` | tls-verification-disabled | 5 | 3 | `rejectUnauthorized: false` |
| `js-secret-aws` | hardcoded-secret | 5 | 3 | `AKIA…` key |
| `js-secret-pem` | hardcoded-secret | 5 | 3 | `BEGIN … PRIVATE KEY` |
| `js-secret-stripe` | hardcoded-secret | 5 | 3 | `sk_live_…` |
| `js-dangerous-html` | xss | 5 | 1 | `dangerouslySetInnerHTML` |

### Java / Kotlin (regex, comment lines skipped)

| Rule | Taxonomy | Blast | Silence | Catches |
|---|---|---|---|---|
| `jvm-exec-injection` | command-injection | 5 | 2 | `Runtime.getRuntime().exec(` or `ProcessBuilder(` with `+` on the same line |
| `jvm-sql-injection` | sql-injection | 5 | 2 | `executeQuery`/`executeUpdate`/`execute` with `+` and a quote on the same line |
| `jvm-empty-catch` | swallowed-exception | 4 | 3 | a `catch (...)` block whose body is empty or comments only |
| `jvm-weak-hash` | weak-hash | 4 | 3 | `MessageDigest.getInstance("MD5")` or `"SHA-1"` |
| `jvm-object-input-stream` | unsafe-deserialization | 5 | 3 | `new ObjectInputStream(` |

The JVM rules are line-local by design: a `+`, a quote, an algorithm name, or a constructor call is either there or it is not. `jvm-empty-catch` reads forward only far enough to prove the body holds nothing but whitespace or comments; an unbalanced block is skipped rather than guessed.

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

Both are visible in the report's "could not determine" section via file counts.

## Adding a rule

1. Add the meta entry in `scripts/lib/rules.py`.
2. Add a fixture line that triggers it and a line that must not.
3. Add a test asserting exactly which rules fire on the fixture.
4. Add the row to this table.

A rule without a negative fixture is a guess.

## Secrets outside source files

Secrets are matched in `.env`, YAML, JSON, Terraform, TOML, INI, `.properties`, and `.conf` as well as source, because that is where they usually are. Source means `.py`, JavaScript/TypeScript, and `.java`/`.kt`/`.kts`, which reuse the same three patterns under the same rule ids. Only the secret rules run on the non-source files; code rules are meaningless there.

| Rule | Where | Matches |
|---|---|---|
| `py-secret-aws` | any scanned file | `AKIA` + 16 characters |
| `py-secret-pem` | any scanned file | a private-key block header |
| `py-secret-stripe` | any scanned file | `sk_live_` + 10 |
| `cfg-secret-generic` | config files only | a credential key assigned a literal value |

The generic rule ignores values that are code references: `process.env.TOKEN`, `os.environ[...]`, and `${VAR}` are not secrets, and masking them would make the evidence say something false.

## Redaction

A finding's `evidence` is quoted verbatim, which means a found secret is a published secret. `report` redacts evidence in `report.json` and `report.html` and lists every redaction in "Could not determine". `out/defects.jsonl` keeps the raw line — the evidence guard needs it — so that file must not be committed or shared. It is not part of the published artifact set.
