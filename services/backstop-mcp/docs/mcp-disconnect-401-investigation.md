# MCP disconnects: Backstop 401 handling

Investigation into a client report of repeated disconnects from `backstop-mcp`, plus a proposal
for the instrumentation needed to close the remaining unknown.

**Status:** investigation complete, instrumentation proposed but **not implemented**. No behaviour
change has been made. This document is the input for that follow-up work.

---

## 1. Summary

Users are being logged out mid-session because Backstop returns **HTTP 401** on ordinary data
endpoints, and a 401 unconditionally revokes every OAuth token belonging to that user.

The original suspicion — that a permission error ("you are not authorized to read this data") was
logging people out — is **not** what is happening. Backstop returned **zero 403s in 30 days**, and
403 does not touch the revoke path anyway.

The open question is *why* Backstop issues those 401s. The evidence says the credential is still
valid: the same credential is rejected and then accepted seconds later. Backstop's own
documentation offers a plausible mechanism, because it documents per-user rate and concurrency
limits but **never documents 429 anywhere**, and defines 401 broadly enough to absorb a limit
breach. We cannot confirm this from production because we discard the 401 response body — which is
precisely the field that would name the cause.

---

## 2. What the logs show

Environment: Grafana `burger` prod, Loki datasource `P8E80F9AEF21F6940`, `app="backstop-mcp"`,
namespace `chat`. Queries are listed in [Appendix A](#appendix-a-queries-used).

### 2.1 The revocation chain

Only 401 is wired to the revoke hook:

`services/backstop-mcp/src/backstop_mcp/backstop_client/client.py:267-277`

```python
if response.status_code == 401:
    # Always surface BackstopAuthError for 401 — a failing revoke hook must not
    # mask the credential rejection callers need to handle (reconnect).
    if self._on_auth_failure is not None:
        try:
            await self._on_auth_failure()
        except Exception:
            logger.exception("backstop.auth_failure_hook.failed")
    raise BackstopAuthError(
        "Backstop rejected the stored credential — please reconnect."
    )
if response.is_error:
    raise BackstopApiError.from_response(response)
```

The hook resolves to `revoke_all_tokens_for_subject`, which stamps `revoked_at` on **every**
non-revoked token for the subject, including the refresh token:

- `backstop_client/factory.py:172` — `on_auth_failure=auth.revoke_current_subject_tokens`
- `features/auth/context.py:69-73` → `dependencies.py:97-98` → `features/auth/provider.py:679-694`

Consequence: the next `/mcp` call returns 401 **and** the client's refresh at `/token` returns 401,
so the client cannot silently recover. It surfaces as a disconnect.

Note the stored Backstop credential in `backstop_credentials` is **not** deleted — only the
MCP-facing OAuth tokens are revoked. There is no code path that deletes a stored credential.

### 2.2 Error distribution (30 days)

| Backstop response | Count | Notes |
| --- | --- | --- |
| 401 on `/system-info` | 14 | login verification only — see 2.4 |
| 401 on data endpoints | 6 | `/quick-search` ×2, `/entity-activities` ×2, `/opportunities`, `/custom-field-definitions` |
| 403 | **0** | permission errors are not occurring at all |
| 404 | 1 | `Resource employees not found by id ...` |
| 429 | **0** | never observed — see section 3 |
| transport (`ReadTimeout`) | 1 | `/meeting-or-calls/{id}/attendees` |

### 2.3 Incident timeline (2026-08-25, UTC)

Every data-endpoint 401 is followed within seconds to minutes by a `/token` 401 and a forced
re-login:

```
14:57:10  401 GET  /quick-search
14:58:27  401 GET  /custom-field-definitions  ->  14:58:27  POST /mcp 401 + POST /token 401
15:00:44  401 POST /entity-activities         ->  15:02:52  POST /mcp 401 + POST /token 401
15:20:05  401 POST /entity-activities         ->  15:25:02  POST /mcp 401 + POST /token 401
15:31:38  401 GET  /opportunities             ->  15:33:50  POST /mcp 401 + POST /token 401
15:43:46  401 GET  /quick-search
```

Four complete logout cycles in one hour. All seven `/token` 401s in the entire 30-day window belong
to this pattern.

### 2.4 The 401s appear spurious, not a credential change

`/system-info` is only ever called from `verify_credential`
(`backstop_client/factory.py:40,188`), so **every 401 on `/system-info` is a failed login attempt**.
Over 30 days: 14 login submissions rejected, 16 accepted.

`POST /backstop/login` returning **200** is the form re-rendered with an error (`_form_response`);
**302** is success (`features/auth/provider.py:400`). Tracking a single login form through its
`request_id` — meaning the same browser tab, same submitted values:

| `request_id` | Attempts |
| --- | --- |
| `jebC7lH1…` | 14:54:42 rejected, 14:55:40 rejected, **14:55:48 accepted** |
| `xCCMKXLp…` | 15:00:11 rejected, 15:00:26 rejected, **15:00:33 accepted** |
| `Y2_vz7BQ…` | 14:46:16 rejected, 14:46:20 rejected, **14:47:00 accepted** |

A user does not correct a mistyped API token in 7–8 seconds, three separate times. The
mid-session 401s are stronger evidence still: those use a stored credential that Backstop had just
accepted at login, with no typing involved.

### 2.5 Ruled out

| Hypothesis | Evidence against |
| --- | --- |
| Backstop 403 → revocation | Zero 403s in 30 days; 403 never reaches the revoke hook |
| Our rate-limit handling misfiring | Zero `backstop.rate_limit.*` events and zero 429s, ever |
| Token retention sweep | `auth.cleanup.purged` reports `oauth_tokens: 0` on every run |
| Refresh-token reuse revoking the family | No reuse events; `/token` 401s all follow a Backstop 401 |
| Multiple replicas each allowing 5 concurrent | Single pod during the incident (`…-mhtxc`, one node) |
| Heavy load from the user | Tool call rate peaked at ~1.4 calls/min |

The load figure deserves a caveat: a *single* tool call fans out into several concurrent Backstop
requests (`get_activity_history` queries multiple activity streams in parallel;
`party_resolver/search_by_email.py` gathers). A low tool rate does not imply low upstream
concurrency.

### 2.6 Observability gaps found

- The 401 response body is discarded. `backstop.request.unauthorized` logs only `method` and `path`.
- No subject/user identifier on any Backstop client log line, so failures cannot be attributed.
- `BackstopAuthError` subclasses plain `Exception` (`backstop_client/errors.py:66`), so FastMCP
  masks it into a generic `ToolError` at the boundary. In Prometheus, `mcp_calls_total` never shows
  a `BackstopAuthError` status — auth failures are indistinguishable from ordinary tool errors.
- The OTel `backstop_*` metrics (`BACKSTOP_REQUESTS`, `BACKSTOP_CONCURRENCY_WAIT`,
  `BACKSTOP_RATE_LIMITED`) are **not** present in the prod Prometheus. Only the generic `mcp_*`
  metrics are scraped, so upstream status codes and concurrency wait cannot be graphed.

---

## 3. What Backstop documents

Sources: Elevio help center (`agent-explore/docs.py`) and this instance's swagger
(`agent-explore/explore.py`).

### 3.1 Status codes — 401 and 403 are defined, 429 is not

"REST API: Status Codes" (article 1286) enumerates 200, 201, 204, 400, 401, 403, 404, 500, 502,
503. **429 does not appear.** Their definitions:

> **401 Unauthorized** — Returned when authentication is required but missing, invalid, **or
> rejected**.
>
> **403 Forbidden** — Returned when the user is authenticated but lacks permission to perform the
> requested action. This could be caused by the user's permission configuration or **data related
> permission restrictions**.

So 403 is exactly the "not authorized to read this data" case, and our handling of it is already
correct. The word "rejected" in the 401 definition is load-bearing: it is broad enough to cover a
request refused for a reason other than a bad credential.

The instance swagger agrees that these are undocumented at the endpoint level. Across all **1167
paths**, the only documented response codes are `400` (1377), `404` (1235), `200` (1160), `413`
(505), `201` (142), `204` (75). There is no 401, 403, or 429 in any endpoint contract, so every
auth-layer response comes from a front layer they never specify.

### 3.2 Rate limits — real, but the status code is deliberately unnamed

"REST API: Rate Limits" (article 1249), quoted in full:

> Our API allows for the following:
> 1,000 requests per minute / 50,000 requests per hour / 500,000 requests per day (24 hours)
> Each API enabled user can have up to **5 concurrent threads**.
> Upon exceeding any of the above limits, you should expect a response **Error code** and body
> indicating that you've either exceeded the **simultaneous usage count** or the allowed access
> limit.

Limits exist, breaching one returns "an Error code" plus an identifying body, and 429 is absent
from their entire documented vocabulary. Whatever a breach returns must therefore be one of the
codes they do list.

### 3.3 Working hypothesis

A per-user rate or concurrency breach is surfaced as **401**, which we interpret as a dead
credential and respond to by revoking the user's tokens.

Supporting points:

- We have never observed a single 429 in 30 days, despite fan-out-heavy usage. Our entire
  rate-limit classification and backoff path keys exclusively on 429
  (`backstop_client/errors.py:118`, `backstop_client/retry.py`) and appears to be dead code in
  production.
- Our concurrency gate is pinned to exactly Backstop's documented ceiling, with no headroom for how
  they count a thread as busy (connection teardown, keep-alive):

  `services/backstop-mcp/src/backstop_mcp/config.py:208-209`

  ```python
  # Backstop hard-limits each user token to 5 concurrent connections.
  max_concurrent_requests_per_user: int = Field(default=5, ge=1)
  ```

- The endpoints that 401'd are precisely our fan-out ones.
- Intermittency, and recovery within seconds, is what a transient limit looks like and is not what a
  revoked credential looks like.

**This is inference, not proof.** Confirming it requires the 401 response body — see section 6.

---

## 4. Where token expiry is configured

From "REST API: Manage Tokens" (article 236):

- **Generating a token** (per user): Main Menu → System Tools → Administrative → Update Your
  Profile → "API Security" section → "Generate New Token". Also reachable via the person icon
  (top right) → "Go to Profile". Users may regenerate as often as they like.
- **Expiry duration** (tenant-wide): Main Menu → System Tools → Administrative → **System Security
  Dashboard**. This is a **Local Administrator** screen.
- Local Administrators can also **force-expire all current tokens** from that dashboard, which
  requires every user to generate a new one. This is intended for a lost or stolen device, and it
  also terminates Excel Toolkit, Backstop Mobile, and Outlook Add-in sessions.

This explains why no expiry is visible from a sandbox user's profile page: the profile page only
offers "Generate New Token". The expiry setting lives on an admin-only, tenant-wide dashboard. If it
has never been configured, tokens do not expire on a schedule.

Worth asking the client's Backstop administrator:

1. Is a token expiry duration configured on the System Security Dashboard, and what is it?
2. Has anyone force-expired tokens recently, and does the timing line up with the reported
   disconnects?

A configured expiry would be a second, independent source of disconnects. It does not explain the
fail-then-succeed-in-8-seconds pattern in section 2.4, so it is complementary rather than an
alternative explanation.

> **Caveat.** The Elevio "Administrative" category (68) is not readable with our docs account —
> `docs.py` returns 401 for it while other categories work, so the script's "session expired"
> message there is misleading. The dashboard details above come from article 236, not from the
> System Security Dashboard article itself.

---

## 5. What API Signing Keys are (and why they are not relevant here)

An **API Signing Key** is a separate mechanism from the API token, layered *on top of* Basic auth
rather than replacing it. Backstop publishes a reference implementation at
[`backstop/backstop-sign-request`](https://github.com/backstop/backstop-sign-request) (MIT, © 2021
Backstop Solutions Group).

How it works:

- The key is a **PKCS#12 (`.p12`) RSA key pair** downloaded from the Backstop **User Profile** page,
  protected by a password chosen at creation. Forget the password and you must generate a new key.
- The client signs `url + RFC1123 Date + request body` (for GET, `url + date` only) using
  `SHA256withRSA`, base64-encodes it, and sends it alongside the normal credentials:

  ```
  Authorization: Basic base64(username:api_token)
  token: true
  Date: Thu, 14 Jan 2021 07:34:54 GMT
  X-Signature: keyId:<p12 filename stem>, algorithm:SHA256withRSA, timeToLive:120, signature:<base64>
  ```

- `timeToLive` is **120 seconds**, so a signature is replay-protected to a 2-minute window.

Constraints, straight from their README:

> The user who calls the API must have a **Security Admin license, and no other licences**.
> Your API allowance must be configured.

The documented example endpoint is `/backstop/api/bulk-system-users` — bulk user provisioning.

**Conclusion:** signing keys gate privileged bulk/admin write operations for Security Admin
accounts. They are not an expiry mechanism, not an alternative to the API token, and not usable by
`backstop-mcp`, which performs per-user reads with an ordinary Basic + `token: true` credential.
They can be set aside for this investigation. Consistent with that, the swagger exposes no
signing-, key-, token-, login-, or session-related endpoints at all.

---

## 6. Proposed instrumentation

Goal: from traces alone, distinguish **transient upstream hiccup** from **genuinely expired or
revoked credential** from **user actually changing their credential**. Items 1, 2 and 4 are
observability only; item 3 changes behaviour.

### 6.1 Log the 401 response body

Today the body is discarded, so the one field that would name the cause is thrown away. Backstop
states the limit-breach response carries "a body indicating that you've either exceeded the
simultaneous usage count or the allowed access limit".

Add to `backstop.request.unauthorized` (`backstop_client/client.py`, alongside the existing
`method`/`path`):

| Field | Notes |
| --- | --- |
| `status_code` | always 401 here, but keeps the shape uniform with `backstop.request.failed` |
| `detail`, `title`, `code` | parsed from the JSON:API `errors[]` envelope, reusing the existing parsing in `errors.py` |
| `body_excerpt` | raw body, truncated (~500 chars), used only when the envelope does not parse |

Redact and cap the excerpt: it is an untrusted upstream string that may echo request content.

**Decision value:** if the body mentions simultaneous usage or an access limit, the concurrency
hypothesis in section 3.3 is confirmed and the fix is to classify it as a rate limit and retry
rather than revoke.

### 6.2 Log whether the credential actually changed at login

On a successful login, compare the submitted API token against the currently stored one before
upserting, and emit a boolean.

| Field | Meaning |
| --- | --- |
| `had_previous_credential` | whether a stored credential existed for this username |
| `credential_changed` | `true` if the submitted token differs from the stored one |

**Never log the token, or a hash of it.** The boolean is the entire signal.

**Decision value:** this is the ground truth for the whole investigation. If users re-login with the
**same** token after a forced logout, the credential was never the problem and we revoked them over
a transient error. If they arrive with a **new** token, the credential really had expired or been
rotated, which points at section 4.

### 6.3 Re-verify before revoking, with a capped backoff

Today a single 401 revokes immediately. Instead, on a mid-session 401, re-probe the same endpoint
the login flow uses (`GET /system-info`, `_VERIFICATION_PATH` in `backstop_client/factory.py:40`)
before deciding.

Proposed shape:

- Probe with retries, **total elapsed capped at ~10 seconds**, then give up.
- **Wait before the first probe** (~1s). If the root cause is concurrency, probing instantly would
  compete for the very budget that is exhausted, and would also let the probe fail for the wrong
  reason. A short delay lets in-flight requests drain.
- Run the probe **outside** the caller's concurrency gate slot, or after releasing it, for the same
  reason.
- Outcome:
  - probe **succeeds** → credential is valid → **do not revoke**; surface a retryable tool error to
    the client and keep the session alive.
  - probe **fails on every attempt** → treat the credential as genuinely rejected → revoke as today.

> **Important design constraint.** `/system-info` itself returned spurious 401s in production — 14
> of 30 login attempts during the incident window. A single-shot probe would therefore confirm a
> false positive roughly half the time. The probe **must** retry with backoff; one attempt is not
> good enough.

Log every probe attempt so the retry shape is visible in traces:

| Field | Meaning |
| --- | --- |
| `trigger_path` | the data endpoint whose 401 started this |
| `attempt` | 1-based probe attempt number |
| `outcome` | `ok` / `unauthorized` / `error` |
| `elapsed_ms` | time since the triggering 401 |
| `revoked` | terminal decision, emitted once |

Suggested message names: `backstop.auth_recheck.attempt` and `backstop.auth_recheck.decision`.

Note that revocation buys very little today: the stored Backstop credential is never deleted, so
keeping the session alive on an unconfirmed 401 does not weaken anything. The cost of a false
positive (an unnecessary logout) is far higher than the cost of a false negative (one failed tool
call).

### 6.4 Supporting changes

- **Attribute failures to a subject.** Add a stable subject/user identifier to the Backstop client
  log lines so 401s can be attributed. Without it we cannot tell one struggling user from several.
- **Scrape the `backstop_*` OTel metrics.** `BACKSTOP_REQUESTS` (has a `status` label),
  `BACKSTOP_CONCURRENCY_WAIT` and `BACKSTOP_RATE_LIMITED` already exist in `metrics.py` but are
  absent from prod Prometheus. `BACKSTOP_CONCURRENCY_WAIT` would directly show whether we are
  sitting at the 5-thread ceiling when the 401s occur — strong independent evidence for section 3.3.
- **Consider lowering `max_concurrent_requests_per_user` to 4** to leave headroom under Backstop's
  documented cap. Cheap, reversible, and testable against the metric above. Not proposed as the fix,
  only as a mitigation while the cause is confirmed.

### 6.5 Reading the resulting traces

| `credential_changed` at next login | Re-probe outcome | Interpretation |
| --- | --- | --- |
| `false` | probe succeeded | Transient upstream hiccup. We must not revoke. |
| `false` | probe failed | Credential rejected but unchanged — points at admin force-expiry (section 4). |
| `true` | probe failed | Genuine rotation or expiry. Current behaviour is correct. |
| `true` | probe succeeded | User rotated the token for unrelated reasons; revocation was still unnecessary. |

---

## 7. Open questions for Backstop support

1. What HTTP status code is returned when a user exceeds the 5 concurrent thread limit, or the
   per-minute / per-hour / per-day request limits? The Rate Limits article says "an Error code" and
   429 does not appear in the Status Codes article.
2. Is a `Retry-After` header ever sent on a limit breach?
3. How is a "concurrent thread" counted — when is a slot released relative to the HTTP response?
4. Can a valid API token be transiently rejected with 401 for reasons other than a bad credential,
   for example during SSO token validation or a load-balancer failover?
5. What is the tenant's configured API token expiry duration, if any?

---

## Appendix A: queries used

Grafana `burger` prod. Loki datasource UID `P8E80F9AEF21F6940`.

Log lines are ANSI-rendered by the collector, so `| json` does not parse them; use line filters and
`regexp` against the rendered line, or read `structuredMetadata.original` for the raw pino JSON.

```logql
# Backstop 401s grouped by upstream path
sum by (bpath) (count_over_time(
  {app="backstop-mcp"} |= "backstop.request.unauthorized"
  | regexp `path=.*?"(?P<bpath>[^"]+)"` [30d]))

# Backstop failures grouped by status code (403s would show here — there are none)
sum by (sc) (count_over_time(
  {app="backstop-mcp"} |= "backstop.request.failed"
  | regexp `status_code=.*?(?P<sc>\d{3})` [30d]))

# MCP endpoint status codes
sum by (code) (count_over_time(
  {app="backstop-mcp"} |= "/mcp HTTP/1.1"
  | regexp `HTTP/1\.1" (?P<code>\d+)` [7d]))

# Login and refresh outcomes: /backstop/login 200 = rejected, 302 = accepted
sum by (ep, code) (count_over_time(
  {app="backstop-mcp"} |~ `"POST /(token|backstop/login)`
  | regexp `"POST /(?P<ep>token|backstop/login)[^"]*" (?P<code>\d+)` [30d]))

# Full incident timeline
{app="backstop-mcp"}
  |~ "backstop\\.request\\.unauthorized|HTTP/1\\.1\" (401|400|403)|/backstop/login|/token|auth\\.login|auth_failure"
  != "oauth-protected-resource" != "oauth-authorization-server"

# Rate limiting / retention sweep (both empty)
{app="backstop-mcp"} |~ `backstop\.rate_limit|backstop\.retry_after|429|auth\.cleanup|auth_failure_hook`
```

Prometheus (datasource `prometheus`) — note `backstop_*` metrics are **not** scraped:

```promql
sum by (status) (increase(mcp_calls_total{job="backstop-mcp"}[2h]))
sum(rate(mcp_calls_total{job="backstop-mcp"}[5m])) * 60
```

## Appendix B: documentation sources

Read via `services/backstop-mcp/agent-explore/` (see the `backstop-api` skill). Elevio articles are
under category 21 (REST API):

| ID | Title | Relevance |
| --- | --- | --- |
| 1286 | REST API: Status Codes | 401 vs 403 definitions; no 429 listed |
| 1249 | REST API: Rate Limits | 1000/min, 50k/hr, 500k/day, 5 concurrent threads |
| 1018 | REST API: Authentication | Basic auth; SSO users use an API token |
| 236 | REST API: Manage Tokens | token generation, expiry duration, force-expiry |
| 1266 | REST API: Headers | required headers including `token: true` |

Instance swagger: `GET {BACKSTOP_BASE_URL}/backstop-api-swagger.json` (1167 paths; documents no
401, 403, or 429).

Signing keys: <https://github.com/backstop/backstop-sign-request>.
