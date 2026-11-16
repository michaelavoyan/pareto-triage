# Entrypoints and reachability

`reach` decides whether a finding matters. Everything here is heuristic — treat it as evidence, not proof.

## Extraction targets

| Kind | How it is found | seed |
|---|---|---|
| HTTP route | framework-specific patterns below, including Django `include(` | 5 |
| Middleware | `app.use('<path>', …)` — on the request path, not a route | 4 |
| Queue consumer | `consumer.subscribe`, `@app.task`, `@shared_task`, `process(` in a worker module | 4 |
| Cron / scheduled | `cron.schedule`, `setInterval`, `@scheduled`, `schedule.every` | 4 |
| CLI command | `package.json` `bin`, `#!/usr/bin/env node`, `if __name__ == "__main__"`, argparse/click/typer | 3 |
| Public API | an `export` or `__all__` in `index.{ts,js}`, `index.tsx`, or `__init__.py` | 3 |

A file that is several things gets the best seed. Each import hop costs one level, down to a floor of 2.

## Framework patterns (v1)

```
Express      app.(get|post|put|patch|delete|use)  ·  router.(get|post|…)
Fastify      fastify.(get|post|…)  ·  fastify.route({
Next.js      files under pages/api/**  ·  app/**/route.{ts,js} exporting GET/POST
FastAPI      @app.(get|post|…)  ·  @router.(get|post|…)
Flask        @app.route  ·  @bp.route  ·  Blueprint.add_url_rule
Django       urls.py entries: path( · re_path( · include(
```

Adding a framework is one regex family plus one fixture. Do not add a framework without a fixture that proves the extraction works.

## Call graph and reach

```
reach = 5  the file registers a route (or is reachable by an include)
reach = 4  middleware, cron, or consumer entrypoint
reach = 3  CLI entrypoint or package export
reach = 2  imported within depth 3 of any seed, floor
reach = 1  present in the repo, no path from any entrypoint
reach = 0  in the repo but unreadable (binary, oversized, non-utf-8)
```

`reach == 0` never attaches to a finding: an unreadable file cannot produce one, and `rank` drops any finding that claims 0. `reach == 1` multiplies impact by 0.25 — dead-code findings are ranked, not discarded, because static reachability is a heuristic.

Path search is static, following imports only. It does not follow dynamic dispatch, dependency injection, reflection, event buses, or string-based routing.

## Resolution

A specifier resolves in this order: a relative path (`./x`, `../y`); a `paths` alias from `tsconfig.json` (`@app/*` → `src/*`) relative to `baseUrl`; a workspace package name from `package.json` `workspaces` (`@acme/lib`); otherwise nothing. An unresolved bare import — `express`, `react` — is dropped, not guessed.

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
| `lang` | `ts`, `js`, or `py` |
| `reach` | file-level, from the graph above |
| `call_path` | entrypoint detail, then each file on the shortest import path, then the function. File-level, not symbol-level — it says which files carry the call, not which functions call which |
| `source` | verbatim lines, capped by `--max-lines` |
| `surrounding` | the file's imports, client construction (`new Client(…)`, `axios.create(…)`), and middleware registration (`app.use(…)`), in file order, quoted as-is, capped at 60 lines. `surrounding_truncated` says when the cap was hit |
| `truncated` | true when the body exceeded the cap. A finding quoting past the cut will fail `validate`, which is the intended signal |

Python bounds come from `ast`. TypeScript and JavaScript bounds come from regex headers plus brace matching that skips strings, template literals, and comments. That is approximate: a mis-parsed arrow function produces a body that fails the evidence check rather than a plausible-looking wrong site.

Overlapping sites are collapsed: when a function is defined inside another, only the inner one is emitted, with `enclosed_by` naming its container. Judging a handler and the closure inside it as two sites would score the same lines twice. `context --include-enclosing` keeps both for anyone who wants the old view.

Default cap is 400 sites, ordered by descending reach, then path and line. The cap is reported; it is never silent. Raise it with `--limit` when a large repo needs a second pass.
