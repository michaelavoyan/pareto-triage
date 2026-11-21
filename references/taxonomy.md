# Failure-mode taxonomy

Thirteen categories. Nothing outside this list is a valid failure-mode finding. Each entry gives the shape, the evidence you must quote, and the case where it is *not* a finding — because the counter-example is what keeps precision above 0.70.

---

## 1. swallowed-exception

**Shape:** `catch` with an empty or log-only body that continues as if the operation succeeded.
**Evidence:** the `catch` block verbatim, plus the line that continues after it.
**Not a finding when:** the operation is genuinely optional (cache write, metrics emit, telemetry) and the caller's contract allows partial success. Quote the caller to prove it.

## 2. missing-timeout

**Shape:** network, database, or subprocess call with no timeout, in a request or job path.
**Evidence:** the call site and the absence of a timeout parameter in the surrounding client config.
**Not a finding when:** the client library applies a default timeout, or the call sits behind a wrapper that sets one.

## 3. no-retry

**Shape:** a single attempt at a fallible remote call, with no retry on a transient failure.
**Evidence:** the call site, and the absence of any retry wrapper around it.
**Not a finding when:** the operation is non-idempotent and a retry would duplicate the effect — that is a deliberate choice, not a defect.

## 4. no-backoff

**Shape:** retries with no delay or jitter, so every client retries at once and the upstream sees a thundering herd.
**Evidence:** the retry loop and the delay expression inside it.
**Not a finding when:** retries are already serialised by a queue, or concurrency is bounded elsewhere on the path.

## 5. missing-idempotency

**Shape:** a webhook handler, payment path, or queue consumer that mutates state without an idempotency key or dedupe check.
**Evidence:** the handler's state mutation and the absence of any key/guard on the path.
**Not a finding when:** the upstream guarantees exactly-once delivery and that guarantee is documented and enforced.

## 6. unbounded-query

**Shape:** a query or collection fetch with no `LIMIT`, no pagination, or a loop issuing one query per row (N+1).
**Evidence:** the query construction and the loop.
**Not a finding when:** the table is provably bounded (config, enum, migration table).

## 7. unbounded-concurrency

**Shape:** `Promise.all` over unbounded input, thread-per-item, or no pool limit on fan-out.
**Evidence:** the fan-out call and the input source.
**Not a finding when:** the input is bounded by a constant or an upstream limit.

## 8. missing-boundary-validation

**Shape:** request body, query param, or file input used without validation before reaching persistence or downstream calls.
**Evidence:** the handler line reading input and the first use that trusts it.
**Not a finding when:** validation sits in middleware the call path demonstrably passes through.

## 9. missing-authz

**Shape:** a route that mutates or reads private data with authentication but no authorization check, or a handler bypassing the common guard.
**Evidence:** the route registration and the handler body showing no ownership/role check.
**Not a finding when:** the route is public by design (health, login, public feed).

## 10. silent-default-fallback

**Shape:** on failure, returns `[]`, `null`, `0`, `{}`, or a stub that the caller cannot distinguish from a real empty result.
**Evidence:** the fallback expression and the caller consuming it.
**Not a finding when:** an empty result is semantically valid and the caller handles it explicitly.

## 11. resource-leak

**Shape:** a file handle, connection, cursor, or timer not released on the error path.
**Evidence:** acquisition plus the error path that skips release.
**Not a finding when:** a `finally`, context manager, or `using` covers every exit.

## 12. non-atomic-write

**Shape:** two or more related writes with no transaction, or a write followed by an external side effect that can fail independently.
**Evidence:** both writes in order.
**Not a finding when:** the operations target independent stores by design and reconciliation exists.

## 13. missing-cancellation

**Shape:** long-running work that ignores request abort, shutdown signal, or client disconnect.
**Evidence:** the loop or await chain with no signal check.
**Not a finding when:** the work is intentionally fire-and-forget and bounded.

---

## Defect-only taxonomies

The thirteen headings above are the complete list of failure modes, and phase 2 may propose nothing outside it. A tool-proven defect may also carry a taxonomy that names the construct rather than a failure shape: `weak-hash` (`MessageDigest` with MD5 or SHA-1) is one. `swallowed-exception` and `missing-timeout` are the overlaps — failure modes here, and the taxonomies of the `jvm-empty-catch`/`jvm-log-only-catch` and `jvm-http-no-timeout` rules. The rule that proves each construct is listed in `references/defect-rules.md`.

## Rejection rules

Drop the finding, do not downgrade it, when:

- evidence cannot be quoted verbatim from the file
- the counter-evidence cannot be stated in one sentence
- reach from an entrypoint is unproven and `reach` would be a guess
- the same finding is already reported by a tool detector (dedupe wins: tools are cheaper to trust)
