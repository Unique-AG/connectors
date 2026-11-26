# Kyckr MCP

An MCP server that searches official company registries and orders registry documents through [Kyckr](https://www.kyckr.com), for KYC and KYB work. Users sign in with Zitadel. Every call to Kyckr uses the one Kyckr API key of the deployment.

## Tools

| Tool | Kyckr endpoint | Cost |
|---|---|---|
| `search_companies` | `GET /companies` | free |
| `get_lite_profile` | `GET /companies/{kyckrId}/lite` | credits |
| `get_enhanced_profile` | `GET /companies/{kyckrId}/enhanced` | credits |
| `list_company_documents` | `GET /companies/{kyckrId}/documents` | free |
| `create_document_order` | `POST /orders` | credits, and creates a real registry order |
| `get_order` | `GET /orders/{orderId}` | free |
| `list_orders` | `GET /orders` | free |

When the order has finished, `create_document_order` and `get_order` also call `GET /orders/{orderId}/download?format=json`. A finished order comes back with its JSON document under `data.documentJson`. Download links are removed. If the filing is PDF only, `details` says so.

The tool descriptions tell the agent to get the user's approval before it calls a tool that spends credits. `create_document_order` needs the user to approve the document and the cost shown by `list_company_documents`.

## Errors

A failed Kyckr call fails the tool call (`isError: true`) with a text such as:

```text
Kyckr answered 404: Company not found. Correlation id: <kyckr-request-id>
```

The correlation id is the Kyckr id of the request. Quote it to Kyckr support. A call that gets no error status from Kyckr, such as a timeout, fails with `The call to Kyckr failed: <error>`.

On a final `429`, one that is not retried or outlasts the retries, the message ends with `(retry after Ns)` when Kyckr sent a whole number of seconds in `Retry-After`. Only a `429` from Kyckr is retried. A `503` can come after Kyckr has charged a paid read, so it is not retried.

## Single tenant

One deployment uses one Kyckr account. Every signed-in user shares its key and its credits. The key is never stored in the database. A deployment that must serve several Kyckr accounts needs a separate deployment per account.

## Configuration

### Secrets

Deliver these from a Kubernetes Secret, never through `values.yaml`, and list the Secret in `extraEnvSecrets` (or use `envVars` with `secretKeyRef`).

| Variable | Notes |
|---|---|
| `UPSTREAM_API_KEY` | The Kyckr API key of this deployment. |
| `ZITADEL_JWT_SIGNING_KEY` | At least 32 characters, the same on every replica. It signs the tokens the MCP issues and encrypts the sign-in state in Postgres. Rotating it signs everyone out. |
| `ZITADEL_CLIENT_SECRET` | Leave unset for a public client with PKCE. |

### Postgres

The base chart sets `DATABASE_URL` and `PG_DATABASE_SSL_MODE` from `postgresql.connection`. The database user needs `CREATE TABLE` rights: the sign-in store creates its table on first use.

With `networkPolicy.enabled`, set `postgresql.connection.host` so the base chart opens Postgres egress. With `connection.url` alone it renders none, because the host sits inside the secret. Then set `postgresql.networkPolicyEgressManaged: true` and add a Postgres rule under `networkPolicy.egress[]`.

### `mcpConfig` (Helm values)

The overlay must set `app.publicBaseUrl`, `zitadel.baseUrl` and `kyckr.apiUrl`: Helm fails with "... is mandatory" without them. The other values are pinned in the chart, and an overlay may change them. An overlay that relied on the old test API default now fails at upgrade and must set `kyckr.apiUrl`.

| Value | Variable | Notes |
|---|---|---|
| `app.publicBaseUrl` | `MCP_BASE_URL` | The public https origin. Must match `routes.hostname`. Mandatory. |
| `zitadel.baseUrl` | `ZITADEL_BASE_URL` | The Zitadel issuer. Mandatory. |
| `zitadel.clientId` | `ZITADEL_CLIENT_ID` | Mandatory in zitadel mode. The client id of the Zitadel application of this MCP. Not a secret. Or supply it through `extraEnvSecrets` or `envVars`. |
| `zitadel.orgId` | `ZITADEL_ORG_ID` | Restricts sign-in to one organisation. See below. |
| `kyckr.apiUrl` | `UPSTREAM_API_URL` | Mandatory, with no default, so no deployment calls the test API by accident. Production is `https://api.kyckr.com/v2`, test is `https://test-api.kyckr.com/v2`. The app rejects every scheme but https, since the Kyckr key goes to this origin. |
| `kyckr.timeoutSeconds` | `UPSTREAM_TIMEOUT_SECONDS` | Pinned at 30. At most 120. |
| `kyckr.defaultCustomerReference` | `UPSTREAM_DEFAULT_CUSTOMER_REFERENCE` | A deployment default, sent to Kyckr on profile, document list and order calls for usage reconciliation. No tool takes it as an argument. |
| `kyckr.defaultContactEmail` | `UPSTREAM_DEFAULT_CONTACT_EMAIL` | A deployment default, the contact on every document order. No tool takes it as an argument. |
| `rateLimit.toolCallsPerWindow` | `MCP_RATE_LIMIT_TOOL_CALLS_PER_WINDOW` | Pinned at 60. Tool calls per signed-in user and window. |
| `rateLimit.windowSeconds` | `MCP_RATE_LIMIT_WINDOW_SECONDS` | Pinned at 60. |

An `UPSTREAM_API_URL` with a path prefix other than `/vN` makes every route `[unknown]` and records no credits.

With `networkPolicy.enabled`, the hosts of `zitadel.baseUrl` and `kyckr.apiUrl` get a Cilium egress rule on port 443, so both URLs are https without a port.

The rate limit is counted in each pod's memory, so N replicas allow N times the limit. The chart keeps `replicaCount: 1` for that reason. With more replicas, divide the limit by the replica count.

The chart also sets `HOST`, `MCP_AUTH_MODE=zitadel` and `DB_SSL_ROOT_CERT` (the CloudNativePG CA from the optional `kyckr-mcp-pg-cluster-ca` secret). `.env.example` lists the rest: log level, `MCP_ALLOWED_ORIGINS`, retry settings and tracing. `MCP_AUTH_MODE=none` turns sign-in off and keeps the server on loopback.

## Sign-in and the organisation restriction

Users sign in with Zitadel through the OIDC proxy of `unique_mcp`. The Zitadel application needs the redirect URI `<MCP_BASE_URL>/auth/callback`.

The application also needs the Refresh Token grant, or Zitadel issues no refresh token and every user signs in again when the access token expires. The MCP asks for `offline_access` at sign-in and lets clients register it, but does not require it, so a token without it is still accepted.

With `ZITADEL_ORG_ID` set, the MCP asks Zitadel for the org scope `urn:zitadel:iam:org:id:<org>` when it sends the user to sign in, so Zitadel can refuse a user of another organisation at login. The MCP also reads `urn:zitadel:iam:user:resourceowner:id` from the verified id token and refuses any other organisation with a 401. If the claim is missing from the id token, every sign-in is refused. Verify in Zitadel which application setting puts it there (possibly "User Info inside ID Token") and check one sign-in before you set `ZITADEL_ORG_ID`.

## Delivering and rotating the Kyckr key

`deploy/terraform/azure/kyckr-mcp-secrets` creates the Key Vault placeholder `manual-kyckr-mcp-upstream-api-key`, valued `<TO BE SET MANUALLY>`. Set it by hand, then map it in the overlay's ExternalSecret.

In the Unique QA overlay pattern, an ExternalSecret writes the secrets into a Kubernetes Secret from Azure Key Vault. The overlay lists that Secret in `extraEnvSecrets`, and each Secret key becomes an environment variable. An example, with placeholders:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: kyckr-mcp-secrets
spec:
  target:
    name: kyckr-mcp-secrets
  data:
    - secretKey: UPSTREAM_API_KEY
      remoteRef:
        key: <secret-name-in-the-store>
      sourceRef:
        storeRef:
          kind: SecretStore
          name: <secret-store-name>
```

Add one `data` entry for `ZITADEL_JWT_SIGNING_KEY`. To rotate the key, write the new value to the store. The Secret changes when the ExternalSecret next refreshes. The Deployment carries `reloader.stakater.com/auto: "true"`, so Reloader then restarts the pods.

## Run locally

```sh
cp .env.example .env
# Set UPSTREAM_API_KEY. MCP_AUTH_MODE=none and HOST=127.0.0.1 are already set.
uv sync
uv run kyckr-mcp
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Without sign-in no database is needed: the dummy `DATABASE_URL` in `.env.example` is enough. `.env.example` sets `UPSTREAM_API_URL` to the Kyckr test API, so no real credits are spent by accident. The app has no default for it and refuses to start without one.

`uv run poe ci` runs every check CI runs.

## Metrics and spans

`/metrics` carries the per-tool metrics every MCP exports (`mcp_calls_total`, `mcp_call_duration_seconds`) and four metrics of this service for calls to Kyckr. They keep the names the NestJS service used.

| Metric | Type | Labels |
|---|---|---|
| `kyckr_api_requests_total` | counter | `method`, `path`, `status` |
| `kyckr_api_request_duration_ms` | histogram | `method`, `path` |
| `kyckr_api_retries_total` | counter | `method`, `path` |
| `kyckr_credits_consumed_total` | counter | `tool` |

- `path` is the route with ids replaced by placeholders: `/companies/:kyckrId/lite`, `/companies/:kyckrId/enhanced`, `/companies/:kyckrId/documents`, `/companies`, `/orders/:orderId`, `/orders/:orderId/download` and `/orders`. The route is read from the encoded path without its query, so an id with a `/` stays one segment. A path outside that list is labelled `[unknown]`. No label carries an id, the Kyckr key or user data.
- `status` is the HTTP status Kyckr answered with, or `0` when it gave no answer, for example on a timeout.
- Each attempt counts, so a request retried after a 429 adds one count per attempt. `kyckr_api_retries_total` adds one for each attempt after the first, so it counts the retries alone.
- The histogram buckets end at 120 000 ms, the longest timeout the chart allows.
- `kyckr_credits_consumed_total` adds the `cost.value` of a successful call to `get_lite_profile`, `get_enhanced_profile`, `create_document_order` or `get_order`. A call that fails, or whose answer has no cost or a cost below 0, adds nothing.
- Each call to Kyckr is a client span named `<method> <route>`, with `http.request.method`, `url.template` and `http.response.status_code`. A status of 400 or more, or no answer, sets the span to error, and no exception message or stack goes on it. Spans export when tracing is on (`OTEL_*`).
- Each attempt that Kyckr answers with an error, or that gets no answer, logs one `WARNING` with its method, route and status, so a retried call can log several.

The old `kyckr_tool_call_duration_ms{tool,result}` is replaced by `mcp_call_duration_seconds{kind,name}`, with the outcome in `mcp_calls_total{status}`.

## Refreshing the spec

The patched spec is vendored at `src/kyckr_mcp/upstream/openapi.yml`, so a restart never depends on Kyckr's site. Lines marked `patched` differ from the published file at `https://developer.kyckr.com/openapi/company_v2.yaml` because the API answers differently.

1. Run `grep -n patched src/kyckr_mcp/upstream/openapi.yml` to list the patched lines, and note the header comment.
2. Download the published file over `openapi.yml`.
3. Apply the `patched` changes again and restore the header comment, or drop a change that Kyckr has fixed.
4. Run `uv run poe codegen`.
5. Review the diff of `src/kyckr_mcp/upstream/generated/`, then run `uv run poe ci`.
