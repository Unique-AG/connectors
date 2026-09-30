{{ template "chart.header" . }}

{{ template "chart.description" . }}

{{ template "chart.homepageLine" . }}

{{ template "chart.maintainersSection" . }}

{{ template "chart.sourcesSection" . }}

{{ template "chart.requirementsSection" . }}

## Installation

Use OCI charts only. Prefer `getunique.azurecr.io`; `uniquecr.azurecr.io` is private and kept for consistency, and GHCR is maintained best-effort.

- `oci://getunique.azurecr.io/helm/a2a-gateway`
- `oci://uniquecr.azurecr.io/connectors/helm/a2a-gateway`
- `oci://ghcr.io/unique-ag/connectors/helm/a2a-gateway`

### Helm

```bash
helm template a2a-gateway \
  oci://getunique.azurecr.io/helm/a2a-gateway \
  --version <version>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)

Pin the chart by OCI digest in GitOps. Keep the version as a comment for humans.

```yaml
spec:
  name: a2a-gateway
  sources:
    - repoURL: oci://getunique.azurecr.io/helm/a2a-gateway
      path: .
      targetRevision: sha256:<chart-digest> # <version>
```

## Deployment notes

### Prerequisites

- Secret `a2a-gateway` with `ENCRYPTION_KEY` (32-byte hex, `openssl rand -hex 32`), or override `envVars`.
- `postgresql.connection` and `rabbitmq.connection` in the cluster overlay.
- The absurd schema and queue. They are not created by the chart (`absurdctl` is a Python tool and not part of the image). Initialise once per database, before the first rollout, with the gateway's `DATABASE_URL`:

  ```bash
  uvx absurdctl init -d "$DATABASE_URL"
  uvx absurdctl create-queue -d "$DATABASE_URL" a2a-gateway
  ```

  The drizzle migrations run in the `migration` pre-install/pre-upgrade hook.

### Exposure through Kong

Enable `extraRoutes.public`, `extraRoutes.callbacks` and `extraRoutes.protected` and set `routes.hostname`. The routes sit at the root of that host, so set `a2aConfig.publicBaseUrl` to `https://<routes.hostname>`; the host must be served by the Kong `Gateway` listener.

| Route | Paths | Auth |
|-------|-------|------|
| `public` | `GET /a2a/agents/{publicationId}/.well-known/agent-card.json`, `GET /.well-known/oauth-protected-resource/a2a` | none |
| `callbacks` | `POST /a2a/callbacks/*` | per-execution token, checked by the gateway |
| `protected` | `/a2a/*`, `/management/*` | `unique-jwt-auth` (cluster plugin) |

`/internal/*` has no route; only node-chat reaches it inside the cluster.

The chart ships three `KongPlugin`s, named after `fullnameOverride`:

- `a2a-gateway-strip-identity` (`request-transformer`) drops caller-supplied `x-user-*`, `x-company-*`, `x-client-id` and `x-service-id` on the unauthenticated routes.
- `a2a-gateway-strip-client` (`request-transformer`) drops caller-supplied `x-client-id`/`x-service-id` on the JWT routes. `unique-jwt-auth` stamps the user identity but does not forward the OAuth client, so tasks are recorded as unattributed until it does.
- `a2a-gateway-request-size` (`request-size-limiting`) enforces `a2aConfig.limits.maxRequestBytes`.

The `protected` route disables response buffering and sets a one-hour read timeout for SSE; keep `konghq.com/read-timeout` in line with `a2aConfig.limits.streamTimeoutMs`.

### NetworkPolicy

With `networkPolicy.enabled`, the CiliumNetworkPolicy allows ingress to the app port from Kong (`internalServices.dependents.ingressGateway`) and node-chat (`internalServices.dependents.chat`), metrics from Prometheus, and egress to DNS, PostgreSQL, RabbitMQ and the Unique services. Egress to remote agents is derived from `a2aConfig.egress.allowedHosts` (also `EGRESS_ALLOWED_HOSTS`), so both stay in sync; add ports other than 443 to `a2aConfig.egress.ports`. With push notifications, `a2aConfig.pushNotifications.allowedHosts` are allowed as well; webhooks to any public host need `networkPolicy.baseline.egress.pushWebhooks.enabled`.

PostgreSQL and RabbitMQ egress is derived from `connection.host`; in URL mode keep `host` set as well.

{{ template "chart.valuesSection" . }}

{{ template "helm-docs.versionFooter" . }}
