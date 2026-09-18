<!-- confluence-space-key: PUBDOC -->

## Prerequisites

kb-mcp has no knowledge-base data of its own: every tool call is a live proxy to your tenant's
Unique API, so a Unique platform subscription is a hard requirement, not just a recommendation.
Where kb-mcp itself runs is flexible: the Helm chart below targets Kubernetes, but the same
Docker image runs on any other cloud or locally. What changes between those is the environment
variables, not the architecture. Zitadel is likewise fixed: it's always the same instance your
Unique AI tenant already uses, never one you stand up yourself.

- Kubernetes 1.25+ with a Gateway API implementation (the chart exposes itself via `HTTPRoute`, not
  a classic `Ingress`)
- Helm 3.x with OCI support
- Postgres 14+ for OAuth-proxy state
- The public (PKCE) OIDC client id for kb-mcp, registered in your tenant's existing Zitadel
  instance
- Network access from kb-mcp's pod to the Unique API instance it calls

## Helm Chart

kb-mcp ships as a standalone Helm chart, published as an OCI artifact alongside every release:

```bash
helm upgrade --install kb-mcp oci://ghcr.io/unique-ag/connectors/helm/kb-mcp \
  --version <version> \
  --namespace <namespace> --create-namespace \
  --values values.yaml
```

The chart lives in `Unique-AG/connectors` under `services/kb-mcp/deploy/helm-charts/kb-mcp`.
Unique's own deployments reference it from ArgoCD by `targetRevision: kb-mcp@<version>`.

## Required Secrets

Three values, none with chart defaults:

| Secret | Purpose |
|---|---|
| `ZITADEL_CLIENT_ID` | Public Zitadel OIDC client id (PKCE, not actually secret) |
| `ZITADEL_JWT_SIGNING_KEY` | Signs kb-mcp's own downstream OAuth-proxy JWTs; never sent to Zitadel |
| `ENCRYPTION_KEY` | Encrypts OAuth-proxy state at rest in Postgres |

Generate the latter two with `openssl rand -hex 32`. `ZITADEL_CLIENT_ID` comes from registering a
public (PKCE) application in Zitadel with redirect URI `{publicBaseUrl}/auth/callback`.

Deliver them via `envVars[].valueFrom.secretKeyRef`, or, at Unique, via `ExternalSecret`s through
`extraEnvSecrets`.

## Minimal Values

```yaml
mcpConfig:
  enabled: true
  app:
    publicBaseUrl: https://kb-mcp.<tenant>.unique.app   # must match routes.hostname
  zitadel:
    baseUrl: https://id.<tenant>.example.com

envVars:
  - name: UNIQUE_API_BASE_URL
    value: http://unique-api.<namespace>.svc.cluster.local

routes:
  hostname: kb-mcp.<tenant>.unique.app
  auth:
    jwt: false   # kb-mcp runs its own OIDC, don't double-gate at the gateway
  paths:
    default: { enabled: true }
    probe: { enabled: true }
```

!!! note "`mcpConfig.zitadel` has no `clientId` field"
    Deliver `ZITADEL_CLIENT_ID` via `envVars` instead. It isn't secret, so a plain `value:` is fine.

## PostgreSQL

Postgres holds OAuth-proxy state only: client registrations, tokens, and JTI mappings. It never
holds knowledge-base data. `postgresql.enabled: true` is the chart default and requires a `DATABASE_URL`.

Either bring an in-cluster CloudNativePG `Cluster` (`postgresql.connection.host.fromKubernetesService`
+ `url.fromSecret`), or point at an external managed instance by supplying `DATABASE_URL` as a
secret env var and setting `postgresql.enabled: false`.

!!! warning "Ephemeral storage is local-development only"
    `ALLOW_EPHEMERAL_OAUTH_STORAGE=true` skips Postgres entirely using a per-process file store.
    State does not survive a restart and is not shared across replicas, so every user is logged out
    on each pod restart.

## Network Policies

`networkPolicy.enabled` defaults to `false` (`flavor: cilium`); set it to `true` for a default-deny
`CiliumNetworkPolicy`. kb-mcp needs egress to DNS, the Unique API, Zitadel and the platform gateway
(the chart ships a baseline `toFQDNs: ["*.unique.app"]` rule), and its Postgres host if external.

!!! warning "`toEndpoints` rules match the pod port, not the Service port"
    Cilium's eBPF Service DNAT happens *before* a `CiliumNetworkPolicy`'s `toEndpoints` rule is
    evaluated, so the rule must allow the container's actual listening port. For kb-mcp calling
    `node-chat`, that means `node-chat`'s container port (`8080`), not its Service port (`8093`).

The monorepo-wide `internalServices` convention encodes this automatically: a chart declaring
`internalServices.dependencies.<key>` gets both the env var and a matching egress rule targeting the
dependency's real pod port, via separate `servicePort`/`podPort` fields.

!!! note "The allowlist is bidirectional"
    Declaring `dependencies` builds only *kb-mcp's* egress rule. `node-chat` must separately
    allowlist kb-mcp under its own `internalServices.dependents.kbMcp`, which defaults to
    `enabled: false`. Otherwise its ingress policy drops the connection silently, with no
    application error, just a timeout.

## Health Checks

`GET /probe` serves all three probes (liveness, readiness, startup).

## Monitoring

- **Logs**: pino-json on stderr, scraped by Loki via the `logging.unique.app/format=pino-json` pod
  label the chart sets by default. Access-log lines for `/probe`, `/health`, and `/metrics` are
  silenced.
- **Metrics/tracing**: opt-in via OpenTelemetry; unset in the chart defaults.

## Troubleshooting

- **Startup hangs under a default-deny network policy**: FastMCP pings `pypi.org` on startup.
  Set `FASTMCP_CHECK_FOR_UPDATES: "off"`.
- **Tool calls hang or time out**: the egress rule is probably targeting the Unique API's Service
  port instead of its pod port. See [Network Policies](#Network-Policies).
- **Server refuses to boot**: kb-mcp requires both `DATABASE_URL` and `ENCRYPTION_KEY` unless
  `ALLOW_EPHEMERAL_OAUTH_STORAGE=true`.
