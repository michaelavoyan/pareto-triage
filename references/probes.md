# Probe templates

One template per failure mode. `verify --scaffold` copies the matching template to
`out/probes/<cluster>.<ext>` so writing a probe is a fill-in-the-blank rather than a
research task.

A scaffold is not a probe. Each copy carries `# scaffold: <hash>` on its first line; while
that hash still matches the template, `verify` reports the cluster as `unverified` with
reason "probe is an unfilled scaffold". Editing the file changes the line or removes it,
and the probe runs.

Rules for every probe:

- Exit non-zero because of the defect, not because of a missing fixture. A probe that
  fails for the wrong reason proves nothing.
- Touch only what the site touches. A probe that rewrites the database is not a probe.
- One probe per cluster. If two clusters need the same test, the clusters are one cluster.

## swallowed-exception

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: call the function with an input that raises, then assert the error surfaces.
raise SystemExit("unfilled scaffold")
```

## missing-timeout

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: point the client at a socket that never answers, then assert the call fails
# within a bounded time instead of hanging.
raise SystemExit("unfilled scaffold")
```

## no-retry

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: make the first attempt fail, then assert a second attempt happens.
raise SystemExit("unfilled scaffold")
```

## no-backoff

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: record attempt timestamps under repeated failure and assert the gap grows.
raise SystemExit("unfilled scaffold")
```

## missing-idempotency

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: deliver the same input twice, then assert the side effect happened once.
raise SystemExit("unfilled scaffold")
```

## unbounded-query

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: grow the input set and assert the result stays bounded or paginated.
raise SystemExit("unfilled scaffold")
```

## unbounded-concurrency

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: submit more work than the limit allows and assert concurrency is capped.
raise SystemExit("unfilled scaffold")
```

## missing-boundary-validation

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: pass a malformed value across the boundary and assert it is rejected.
raise SystemExit("unfilled scaffold")
```

## missing-authz

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: call the path without the required identity and assert refusal.
raise SystemExit("unfilled scaffold")
```

## silent-default-fallback

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: make the primary source fail and assert the caller learns about it.
raise SystemExit("unfilled scaffold")
```

## resource-leak

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: repeat the operation and assert the handle, pool, or connection is released.
raise SystemExit("unfilled scaffold")
```

## non-atomic-write

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: interrupt the write midway and assert the store is not half-written.
raise SystemExit("unfilled scaffold")
```

## missing-cancellation

```
# scaffold: {{hash}}
# Cluster: {{cluster}} — {{file}}:{{line}} ({{function}})
# TODO: cancel the parent task and assert the child stops.
raise SystemExit("unfilled scaffold")
```
