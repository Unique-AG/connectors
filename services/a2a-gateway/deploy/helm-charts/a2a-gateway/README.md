# a2a-gateway

Optional bidirectional A2A gateway for Unique

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/unique-ag/helm | base | 0.1.0-87990c |

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

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| a2aConfig | object | `{"corsAllowedOrigins":[],"egress":{"allowedHosts":[],"ports":["443"]},"enabled":true,"limits":{"elicitationTimeoutSeconds":600,"maxActiveExecutionsPerConnection":20,"maxActiveExecutionsPerTenant":50,"maxActiveTasksPerTenant":50,"maxRemoteFileBytes":52428800,"maxRequestBytes":26214400,"streamTimeoutMs":3600000},"publicBaseUrl":"{{ fail \"a2aConfig.publicBaseUrl is mandatory. Override in your deployment values.\" }}","pushNotifications":{"allowedHosts":[],"enabled":false},"reconcileIntervalSeconds":300,"retention":{"executionDays":30,"taskDays":30},"unique":{"chatUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.chat) }}","ingestionUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}","scopeManagementUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}"},"worker":{"concurrency":32,"enabled":true},"zitadelIssuer":"{{ fail \"a2aConfig.zitadelIssuer is mandatory. Override in your deployment values.\" }}"}` | Configuration of the A2A gateway, mapped to environment variables |
| a2aConfig.corsAllowedOrigins | list | `[]` | Allowed browser origins, e.g. the Unique admin frontend. example: [https://admin.unique.app] |
| a2aConfig.egress.allowedHosts | list | `[]` | Operator-approved remote agent and token endpoint hostnames (exact match, HTTPS only). Empty denies all outbound agent traffic. The CiliumNetworkPolicy allows the same hosts. |
| a2aConfig.egress.ports | list | `["443"]` | Ports the CiliumNetworkPolicy opens for allowedHosts |
| a2aConfig.limits.maxRequestBytes | int | `26214400` | Request body limit; also enforced by Kong on the protected and callback routes. |
| a2aConfig.publicBaseUrl | string | `"{{ fail \"a2aConfig.publicBaseUrl is mandatory. Override in your deployment values.\" }}"` | Kong-facing HTTPS base URL, used for agent cards, file URLs and callbacks. example: https://a2a.unique.app |
| a2aConfig.pushNotifications.allowedHosts | list | `[]` | Limit client webhooks to these hostnames; empty allows any public HTTPS host. The CiliumNetworkPolicy allows these hosts on a2aConfig.egress.ports; any host needs networkPolicy.baseline.egress.pushWebhooks. |
| a2aConfig.unique | object | `{"chatUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.chat) }}","ingestionUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}","scopeManagementUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}"}` | Unique services; auto-derived from internalServices.dependencies (node-chat appends /graphql). |
| a2aConfig.zitadelIssuer | string | `"{{ fail \"a2aConfig.zitadelIssuer is mandatory. Override in your deployment values.\" }}"` | Zitadel issuer URL, advertised in the OAuth protected-resource metadata. example: https://id.unique.app |
| deployment.metadata.annotations."reloader.stakater.com/auto" | string | `"true"` |  |
| deployment.revisionHistoryLimit | int | `3` |  |
| env.AUTH_MODE | string | `"kong"` |  |
| env.NODE_ENV | string | `"production"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"9564"` |  |
| env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| envVars | list | `[{"name":"ENCRYPTION_KEY","valueFrom":{"secretKeyRef":{"key":"ENCRYPTION_KEY","name":"a2a-gateway"}}}]` | Environment variables from secrets |
| extraRoutes.callbacks.annotations."konghq.com/plugins" | string | `"a2a-gateway-strip-identity,a2a-gateway-request-size,unique-route-metrics"` |  |
| extraRoutes.callbacks.enabled | bool | `false` |  |
| extraRoutes.callbacks.hostnames[0] | string | `"{{ .Values.routes.hostname }}"` |  |
| extraRoutes.callbacks.matches[0].method | string | `"POST"` |  |
| extraRoutes.callbacks.matches[0].path.type | string | `"PathPrefix"` |  |
| extraRoutes.callbacks.matches[0].path.value | string | `"/a2a/callbacks"` |  |
| extraRoutes.protected.annotations."konghq.com/plugins" | string | `"unique-jwt-auth,a2a-gateway-strip-client,a2a-gateway-request-size,unique-route-metrics"` |  |
| extraRoutes.protected.annotations."konghq.com/read-timeout" | string | `"3600000"` |  |
| extraRoutes.protected.annotations."konghq.com/response-buffering" | string | `"false"` |  |
| extraRoutes.protected.enabled | bool | `false` |  |
| extraRoutes.protected.hostnames[0] | string | `"{{ .Values.routes.hostname }}"` |  |
| extraRoutes.protected.matches[0].path.type | string | `"PathPrefix"` |  |
| extraRoutes.protected.matches[0].path.value | string | `"/a2a"` |  |
| extraRoutes.protected.matches[1].path.type | string | `"PathPrefix"` |  |
| extraRoutes.protected.matches[1].path.value | string | `"/management"` |  |
| extraRoutes.public.annotations."konghq.com/plugins" | string | `"a2a-gateway-strip-identity,unique-route-metrics"` |  |
| extraRoutes.public.enabled | bool | `false` |  |
| extraRoutes.public.hostnames[0] | string | `"{{ .Values.routes.hostname }}"` |  |
| extraRoutes.public.matches[0].method | string | `"GET"` |  |
| extraRoutes.public.matches[0].path.type | string | `"RegularExpression"` |  |
| extraRoutes.public.matches[0].path.value | string | `"^/a2a/agents/pub_[0-9a-z]+/\\.well-known/agent-card\\.json$"` |  |
| extraRoutes.public.matches[1].method | string | `"GET"` |  |
| extraRoutes.public.matches[1].path.type | string | `"Exact"` |  |
| extraRoutes.public.matches[1].path.value | string | `"/.well-known/oauth-protected-resource/a2a"` |  |
| fullnameOverride | string | `"a2a-gateway"` |  |
| hooks.migration.command | string | `"cd /app && ./node_modules/.bin/drizzle-kit migrate\n"` |  |
| hooks.migration.enabled | bool | `true` |  |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.registry | string | `"ghcr.io"` |  |
| image.repository | string | `"unique-ag/connectors/services/a2a-gateway"` |  |
| image.tag | string | `"0.0.0"` |  |
| internalServices.dependencies.chat.name | string | `"chat"` |  |
| internalServices.dependencies.chat.podPort | int | `8080` |  |
| internalServices.dependencies.chat.servicePort | int | `8093` |  |
| internalServices.dependencies.ingestion.name | string | `"ingestion"` |  |
| internalServices.dependencies.ingestion.podPort | int | `8080` |  |
| internalServices.dependencies.ingestion.servicePort | int | `8091` |  |
| internalServices.dependencies.scopeManagement.name | string | `"scope-management"` |  |
| internalServices.dependencies.scopeManagement.podPort | int | `8080` |  |
| internalServices.dependencies.scopeManagement.servicePort | int | `8094` |  |
| internalServices.dependents.chat.name | string | `"chat"` |  |
| internalServices.dependents.ingressGateway.name | string | `"gateway"` |  |
| internalServices.dependents.ingressGateway.namespace | string | `"system"` |  |
| nameOverride | string | `"a2a-gateway"` |  |
| networkPolicy.baseline.egress.pushWebhooks.enabled | bool | `false` |  |
| networkPolicy.baseline.egress.pushWebhooks.toEntities[0] | string | `"world"` |  |
| networkPolicy.baseline.egress.pushWebhooks.toPorts[0].ports[0].port | string | `"443"` |  |
| networkPolicy.baseline.egress.pushWebhooks.toPorts[0].ports[0].protocol | string | `"TCP"` |  |
| networkPolicy.baseline.prometheus.namespace | string | `"system"` |  |
| networkPolicy.enableDefaultDeny.egress | bool | `true` |  |
| networkPolicy.enableDefaultDeny.ingress | bool | `true` |  |
| networkPolicy.enabled | bool | `false` |  |
| networkPolicy.flavor | string | `"cilium"` |  |
| pdb.maxUnavailable | int | `1` |  |
| podLabels."logging.unique.app/format" | string | `"pino-json"` |  |
| ports.application | int | `9560` |  |
| ports.metrics | int | `9564` |  |
| postgresql.connection.sslMode | string | `"verify"` |  |
| postgresql.enabled | bool | `true` |  |
| probes.enabled | bool | `true` |  |
| probes.liveness.failureThreshold | int | `6` |  |
| probes.liveness.httpGet.path | string | `"/health/live"` |  |
| probes.liveness.httpGet.port | string | `"http"` |  |
| probes.liveness.periodSeconds | int | `10` |  |
| probes.readiness.failureThreshold | int | `3` |  |
| probes.readiness.httpGet.path | string | `"/health/ready"` |  |
| probes.readiness.httpGet.port | string | `"http"` |  |
| probes.readiness.periodSeconds | int | `10` |  |
| probes.readiness.timeoutSeconds | int | `5` |  |
| probes.startup.failureThreshold | int | `30` |  |
| probes.startup.httpGet.path | string | `"/health/live"` |  |
| probes.startup.httpGet.port | string | `"http"` |  |
| probes.startup.periodSeconds | int | `5` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.alert | string | `"A2aGatewayQuotaRejections"` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.annotations.description | string | `"Company {{ $labels.company_id }} hit the {{ $labels.scope }} quota {{ $value }} times in 15 minutes ({{ $labels.direction }})."` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.annotations.runbook | string | `"1. Check whether the company runs unusually many concurrent A2A runs\n2. Raise a2aConfig.limits.maxActive* if the load is legitimate\n"` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.annotations.summary | string | `"A2A gateway rejects requests by quota"` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.expr | string | `"sum by (company_id, direction, scope) (increase(a2a_gateway_quota_rejections_total[15m])) > 50\n"` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.for | string | `"15m"` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.labels.alertGroup | string | `"a2a-gateway"` |  |
| prometheus.additionalAlerts.A2aGatewayQuotaRejections.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.alert | string | `"A2aGatewayRunFailureRate"` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.annotations.description | string | `"{{ $value | humanizePercentage }} of {{ $labels.direction }} A2A runs finished as failed or unknown."` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.annotations.runbook | string | `"1. Inspect gateway logs for failed runs\n2. Check remote agent availability and credentials\n3. Check the Unique services the gateway depends on\n"` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.annotations.summary | string | `"A2A gateway run failure rate is high"` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.expr | string | `"(\n  sum by (direction) (rate(a2a_gateway_runs_finished_total{state=~\"failed|unknown\"}[15m]))\n  /\n  sum by (direction) (rate(a2a_gateway_runs_finished_total[15m]))\n) > 0.1\n"` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.for | string | `"15m"` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.labels.alertGroup | string | `"a2a-gateway"` |  |
| prometheus.additionalAlerts.A2aGatewayRunFailureRate.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.alert | string | `"A2aGatewayStuckRuns"` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.annotations.description | string | `"{{ $value }} {{ $labels.direction }} A2A runs of company {{ $labels.company_id }} made no progress beyond the recovery threshold."` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.annotations.runbook | string | `"1. Inspect gateway logs for the affected company and direction\n2. Check that the remote agents are reachable and approved in EGRESS_ALLOWED_HOSTS\n3. Check the absurd worker (WORKER_ENABLED) and the /health/ready endpoint\n"` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.annotations.summary | string | `"A2A gateway runs are stuck"` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.expr | string | `"max by (company_id, direction) (a2a_gateway_stuck_runs) > 0\n"` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.for | string | `"30m"` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.labels.alertGroup | string | `"a2a-gateway"` |  |
| prometheus.additionalAlerts.A2aGatewayStuckRuns.labels.severity | string | `"warning"` |  |
| rabbitmq.connection | object | `{}` |  |
| rabbitmq.enabled | bool | `true` |  |
| replicaCount | int | `1` |  |
| resources.limits.memory | string | `"1Gi"` |  |
| resources.requests.cpu | string | `"250m"` |  |
| resources.requests.memory | string | `"512Mi"` |  |
| routes.hostname | string | `""` | Kong-facing hostname, e.g. a2a.unique.app |
| selectorComponentLabel | string | `"server"` |  |
| service.port | int | `80` |  |
| serviceAccount.enabled | bool | `true` |  |
| volumeMounts[0].mountPath | string | `"/tmp"` |  |
| volumeMounts[0].name | string | `"tmp"` |  |
| volumes[0].emptyDir.sizeLimit | string | `"1Gi"` |  |
| volumes[0].name | string | `"tmp"` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
