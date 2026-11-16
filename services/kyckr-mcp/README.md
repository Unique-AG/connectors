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

The tool descriptions tell the agent to confirm with the user before it calls a tool that spends credits.

## Errors

A failed Kyckr call does not raise an MCP error. The tool answers:

```json
{ "success": false, "statusCode": 404, "message": "Company not found", "correlationId": "<kyckr-request-id>" }
```

`correlationId` is the Kyckr id of the request. Quote it to Kyckr support.

Only a `429` from Kyckr is retried. A `503` can come after Kyckr has charged a paid read, so it is not retried.

## Single tenant

One deployment uses one Kyckr account. Every signed-in user shares its key and its credits. The key is never stored in the database. A deployment that must serve several Kyckr accounts needs a separate deployment per account.

## Configuration

### Secrets

Deliver these from a Kubernetes Secret, never through `values.yaml`, and list the Secret in `extraEnvSecrets` (or use `envVars` with `secretKeyRef`).

| Variable | Notes |
|---|---|
| `UPSTREAM_API_KEY` | The Kyckr API key of this deployment. |
| `ZITADEL_CLIENT_ID` | The client id of the Zitadel application of this MCP. |
| `ZITADEL_JWT_SIGNING_KEY` | At least 32 characters, the same on every replica. It signs the tokens the MCP issues and encrypts the sign-in state in Postgres. Rotating it signs everyone out. |
| `ZITADEL_CLIENT_SECRET` | Leave unset for a public client with PKCE. |

### Postgres

The base chart sets `DATABASE_URL` and `PG_DATABASE_SSL_MODE` from `postgresql.connection`. The database user needs `CREATE TABLE` rights: the sign-in store creates its table on first use.

With `networkPolicy.enabled`, set `postgresql.connection.host` so the base chart opens Postgres egress. With `connection.url` alone it renders none, because the host sits inside the secret. Then set `postgresql.networkPolicyEgressManaged: true` and add a Postgres rule under `networkPolicy.egress[]`.

### `mcpConfig` (Helm values)

Unset values use the app default.

| Value | Variable | Notes |
|---|---|---|
| `app.publicBaseUrl` | `MCP_BASE_URL` | The public https origin. Must match `routes.hostname`. Required. |
| `zitadel.baseUrl` | `ZITADEL_BASE_URL` | The Zitadel issuer. Required. |
| `zitadel.orgId` | `ZITADEL_ORG_ID` | Restricts sign-in to one organisation. See below. |
| `kyckr.apiUrl` | `UPSTREAM_API_URL` | The chart sets the test API, `https://test-api.kyckr.com/v2`. Production is `https://api.kyckr.com/v2`. |
| `kyckr.timeoutSeconds` | `UPSTREAM_TIMEOUT_SECONDS` | At most 120. |
| `kyckr.defaultCustomerReference` | `UPSTREAM_DEFAULT_CUSTOMER_REFERENCE` | Sent to Kyckr for usage reconciliation when a call gives none. |
| `kyckr.defaultContactEmail` | `UPSTREAM_DEFAULT_CONTACT_EMAIL` | The contact on a document order when a call gives none. |
| `rateLimit.toolCallsPerWindow` | `MCP_RATE_LIMIT_TOOL_CALLS_PER_WINDOW` | Tool calls per signed-in user and window. |
| `rateLimit.windowSeconds` | `MCP_RATE_LIMIT_WINDOW_SECONDS` | |

With `networkPolicy.enabled`, the hosts of `zitadel.baseUrl` and `kyckr.apiUrl` get a Cilium egress rule on port 443, so both URLs are https without a port.

The rate limit is counted in each pod's memory, so N replicas allow N times the limit. The chart keeps `replicaCount: 1` for that reason. With more replicas, divide the limit by the replica count.

The chart also sets `HOST`, `MCP_AUTH_MODE=zitadel` and `DB_SSL_ROOT_CERT` (the CloudNativePG CA from the optional `kyckr-mcp-pg-cluster-ca` secret). `.env.example` lists the rest: log level, `MCP_ALLOWED_ORIGINS`, retry settings and tracing. `MCP_AUTH_MODE=none` turns sign-in off and keeps the server on loopback.

## Sign-in and the organisation restriction

Users sign in with Zitadel through the OIDC proxy of `unique_mcp`. The Zitadel application needs the redirect URI `<MCP_BASE_URL>/auth/callback`.

With `ZITADEL_ORG_ID` set, the MCP reads `urn:zitadel:iam:user:resourceowner:id` from the verified id token and refuses any other organisation with a 401. If the claim is missing from the id token, every sign-in is refused. Verify in Zitadel which application setting puts it there (possibly "User Info inside ID Token") and check one sign-in before you set `ZITADEL_ORG_ID`.

## Delivering and rotating the Kyckr key

In the Unique QA overlay pattern, an ExternalSecret writes the secrets into a Kubernetes Secret from Azure Key Vault. The overlay lists that Secret in `extraEnvSecrets`, and each Secret key becomes an environment variable. An example, with placeholders:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
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

Add one `data` entry for each of `ZITADEL_CLIENT_ID` and `ZITADEL_JWT_SIGNING_KEY`. To rotate the key, write the new value to the store. The Secret changes when the ExternalSecret next refreshes. The Deployment carries `reloader.stakater.com/auto: "true"`, so Reloader then restarts the pods.

## Run locally

```sh
cp .env.example .env
# Set UPSTREAM_API_KEY. MCP_AUTH_MODE=none and HOST=127.0.0.1 are already set.
uv sync
uv run kyckr-mcp
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Without sign-in no database is needed: the dummy `DATABASE_URL` in `.env.example` is enough. The default `UPSTREAM_API_URL` is the Kyckr test API, so no real credits are spent by accident.

`uv run poe ci` runs every check CI runs.

## Not ported

The old service exported `kyckr_api_requests_total`, `kyckr_api_request_duration_ms` and `kyckr_credits_consumed_total`, and traced each Kyckr call. This service has the shared per-tool metrics of `mcp-observability` only.
