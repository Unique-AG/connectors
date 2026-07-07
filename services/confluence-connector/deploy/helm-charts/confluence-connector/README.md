# confluence-connector

Take content from Confluence and send it to Unique AI for RAG ingestion.

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/unique-ag/helm | base | 0.1.0-4c70c3 |

## Installation

Use OCI charts only. Prefer `getunique.azurecr.io`; `uniquecr.azurecr.io` is private and kept for consistency, and GHCR is maintained best-effort.

- `oci://getunique.azurecr.io/helm/confluence-connector`
- `oci://uniquecr.azurecr.io/connectors/helm/confluence-connector`
- `oci://ghcr.io/unique-ag/connectors/helm/confluence-connector`

### Helm

```bash
helm template confluence-connector \
  oci://getunique.azurecr.io/helm/confluence-connector \
  --version <version>
```

### [`helmfile`](https://helmfile.readthedocs.io)

```yaml
# helmfile version v1.1.7
releases:
  - name: confluence-connector
    chart: oci://getunique.azurecr.io/helm/confluence-connector
    version: <version>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)

Pin the chart by OCI digest in GitOps. Keep the version as a comment for humans.

```yaml
spec:
  name: confluence-connector
  sources:
    - repoURL: oci://getunique.azurecr.io/helm/confluence-connector
      path: .
      targetRevision: sha256:<chart-digest> # <version>
```

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| connectorConfig.enabled | bool | `true` | if disabled, tenant-config must be removed from volumes and volumeMounts |
| connectorConfig.tenants[0].confluence.apiRateLimitPerMinute | int | `1200` | Number of Confluence API requests allowed per minute Atlassian recommends DC admins allow at least 20 req/s (1200 RPM). Cloud uses a points-based quota. |
| connectorConfig.tenants[0].confluence.auth.clientId | string | `"{{ fail \"confluence.auth.clientId is mandatory when auth.mode is oauth_2lo. Override in your deployment values.\" }}"` | OAuth 2.0 (2LO) application client ID |
| connectorConfig.tenants[0].confluence.auth.clientSecret | string | `"os.environ/CONFLUENCE_CLIENT_SECRET"` | OAuth 2.0 client secret. Use "os.environ/ENV_VAR_NAME" to read from environment variable at runtime. This default is overridden per-tenant in the monorepo app.yaml values. |
| connectorConfig.tenants[0].confluence.auth.mode | string | `"oauth_2lo"` | authentication mode possible values: oauth_2lo |
| connectorConfig.tenants[0].confluence.baseUrl | string | `"{{ fail \"confluence.baseUrl is mandatory. Override in your deployment values.\" }}"` | base url of the Confluence instance example (cloud): https://acme.atlassian.net example (data-center): https://confluence.acme.com |
| connectorConfig.tenants[0].confluence.cloudId | string | `"{{ fail \"confluence.cloudId is mandatory when instanceType is cloud. Override in your deployment values.\" }}"` | Atlassian Cloud ID (UUID) for the Confluence site (required for cloud instances) |
| connectorConfig.tenants[0].confluence.ingestAllLabel | string | `"ai-ingest-all"` | Label to trigger full sync of all labeled pages |
| connectorConfig.tenants[0].confluence.ingestSingleLabel | string | `"ai-ingest"` | Label to trigger single-page sync |
| connectorConfig.tenants[0].confluence.instanceType | string | `"cloud"` | Confluence instance type: cloud or data-center |
| connectorConfig.tenants[0].ingestion.ingestionMode | string | `"flat"` | Ingestion traversal mode |
| connectorConfig.tenants[0].ingestion.scopeId | string | `"{{ fail \"ingestion.scopeId is mandatory. Override in your deployment values.\" }}"` | Root scope ID for ingestion |
| connectorConfig.tenants[0].ingestion.storeInternally | string | `"enabled"` | Whether to store content internally in Unique |
| connectorConfig.tenants[0].ingestion.useV1KeyFormat | string | `"disabled"` | Use v1-compatible ingestion key format (spaceId_spaceKey/pageId) without tenant prefix |
| connectorConfig.tenants[0].name | string | `"default"` |  |
| connectorConfig.tenants[0].processing.concurrency | int | `1` | how many pages you want to submit for ingestion into Unique at once |
| connectorConfig.tenants[0].processing.scanIntervalCron | string | `"*/15 * * * *"` | cron expression for the scheduled Confluence scan interval default: every 15 minutes |
| connectorConfig.tenants[0].unique.apiRateLimitPerMinute | int | `100` | Number of Unique API requests allowed per minute |
| connectorConfig.tenants[0].unique.authMode | string | `"cluster_local"` | communication mode for the Unique Services possible values: cluster_local, external cluster_local: communicates using in-cluster URLs and requires serviceExtraHeaders with x-company-id and x-user-id external: communicates using external URLs and requires authentication via Zitadel |
| connectorConfig.tenants[0].unique.ingestionServiceBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}"` | base URL for the ingestion service; auto-derived from internalServices.dependencies.ingestion override with an explicit URL when authMode is external, e.g. https://api.unique.app/ingestion |
| connectorConfig.tenants[0].unique.scopeManagementServiceBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}"` | base URL for the scope management service; auto-derived from internalServices.dependencies.scopeManagement override with an explicit URL when authMode is external, e.g. https://api.unique.app/scope-management |
| connectorConfig.tenants[0].unique.serviceExtraHeaders | object | `{"x-company-id":"{{ fail \"unique.serviceExtraHeaders.x-company-id is mandatory when authMode is cluster_local. Override in your deployment values.\" }}","x-user-id":"{{ fail \"unique.serviceExtraHeaders.x-user-id is mandatory when authMode is cluster_local. Override in your deployment values.\" }}"}` | Object containing extra HTTP headers for Unique API requests (GraphQL and REST) Required when authMode is cluster_local. Must contain x-company-id and x-user-id headers. example: {"x-company-id": "1234567890", "x-user-id": "1234567890"} |
| connectorConfig.tenants[0].unique.zitadel | object | `{"clientId":"{{ fail \"unique.zitadel.clientId is mandatory when authMode is external. Override in your deployment values.\" }}","oauthTokenUrl":"{{ fail \"unique.zitadel.oauthTokenUrl is mandatory when authMode is external. Override in your deployment values.\" }}","projectId":"{{ fail \"unique.zitadel.projectId is mandatory when authMode is external. Override in your deployment values.\" }}"}` | Zitadel authentication configuration (required when authMode is external) |
| connectorConfig.tenants[0].unique.zitadel.clientId | string | `"{{ fail \"unique.zitadel.clientId is mandatory when authMode is external. Override in your deployment values.\" }}"` | Zitadel client ID |
| connectorConfig.tenants[0].unique.zitadel.oauthTokenUrl | string | `"{{ fail \"unique.zitadel.oauthTokenUrl is mandatory when authMode is external. Override in your deployment values.\" }}"` | Zitadel OAuth token URL example: https://idp.unique.app/oauth/v2/token |
| connectorConfig.tenants[0].unique.zitadel.projectId | string | `"{{ fail \"unique.zitadel.projectId is mandatory when authMode is external. Override in your deployment values.\" }}"` | Zitadel project ID example: 225317577440629999 |
| deployment.metadata.annotations."reloader.stakater.com/auto" | string | `"true"` |  |
| deployment.revisionHistoryLimit | int | `3` |  |
| env.HEALTH_CONNECTIVITY_TIMEOUT_MS | string | `"3000"` |  |
| env.HEALTH_SYNC_HISTORY_SIZE | string | `"5"` |  |
| env.HEALTH_SYNC_TENANT_FAILURE_THRESHOLD | string | `"0.5"` |  |
| env.LOGS_DIAGNOSTICS_DATA_POLICY | string | `"conceal"` |  |
| env.LOG_LEVEL | string | `"info"` |  |
| env.MAX_HEAP_MB | int | `1920` |  |
| env.NODE_ENV | string | `"production"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"51350"` |  |
| env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| env.TENANT_CONFIG_PATH_PATTERN | string | `"/app/tenant-configs/*-tenant-config.yaml"` |  |
| envVars | list | `[]` | Environment variables from secrets. Example for loading secrets (uncomment and customize as needed):   envVars:     # For Zitadel authentication (required when authMode is 'external')     - name: ZITADEL_CLIENT_SECRET       valueFrom:         secretKeyRef:           name: confluence-connector-secret           key: ZITADEL_CLIENT_SECRET     # For Confluence OAuth 2.0 (2LO) client secret     - name: CONFLUENCE_CLIENT_SECRET       valueFrom:         secretKeyRef:           name: confluence-connector-secret           key: CONFLUENCE_CLIENT_SECRET     # For proxy basic auth password (required when proxy.authMode is 'username_password')     - name: PROXY_PASSWORD       valueFrom:         secretKeyRef:           name: confluence-connector-secret           key: PROXY_PASSWORD |
| extraEnvCM | list | `["confluence-connector-proxy-config"]` | List of ConfigMaps to load as environment variables. |
| fullnameOverride | string | `"confluence-connector"` |  |
| grafana.dashboard.enabled | bool | `false` | Enable Grafana dashboard ConfigMap creation |
| grafana.dashboard.folder | string | `"connectors"` | Grafana folder where the dashboard will be placed |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.registry | string | `"ghcr.io"` |  |
| image.repository | string | `"unique-ag/connectors/services/confluence-connector"` |  |
| image.tag | string | `"2.2.0"` |  |
| internalServices.dependencies.ingestion.name | string | `"ingestion"` |  |
| internalServices.dependencies.ingestion.podPort | int | `8080` |  |
| internalServices.dependencies.ingestion.servicePort | int | `8091` |  |
| internalServices.dependencies.scopeManagement.name | string | `"scope-management"` |  |
| internalServices.dependencies.scopeManagement.podPort | int | `8080` |  |
| internalServices.dependencies.scopeManagement.servicePort | int | `8094` |  |
| nameOverride | string | `"confluence-connector"` |  |
| networkPolicy.baseline.egress.atlassian.toFQDNs[0].matchPattern | string | `"*.atlassian.net"` |  |
| networkPolicy.baseline.egress.atlassian.toFQDNs[1].matchName | string | `"api.atlassian.com"` |  |
| networkPolicy.baseline.egress.atlassian.toFQDNs[2].matchName | string | `"auth.atlassian.com"` |  |
| networkPolicy.baseline.egress.atlassian.toFQDNs[3].matchName | string | `"api.media.atlassian.com"` |  |
| networkPolicy.baseline.egress.atlassian.toPorts[0].ports[0].port | string | `"443"` |  |
| networkPolicy.baseline.egress.atlassian.toPorts[0].ports[0].protocol | string | `"TCP"` |  |
| networkPolicy.baseline.prometheus.namespace | string | `"system"` |  |
| networkPolicy.enableDefaultDeny.egress | bool | `true` |  |
| networkPolicy.enableDefaultDeny.ingress | bool | `true` |  |
| networkPolicy.enabled | bool | `false` |  |
| networkPolicy.flavor | string | `"cilium"` |  |
| podLabels."logging.unique.app/format" | string | `"pino-json"` |  |
| ports.application | int | `51349` |  |
| ports.metrics | int | `51350` |  |
| probes.enabled | bool | `true` |  |
| probes.liveness.failureThreshold | int | `6` |  |
| probes.liveness.httpGet.path | string | `"/probe"` |  |
| probes.liveness.httpGet.port | string | `"http"` |  |
| probes.liveness.initialDelaySeconds | int | `10` |  |
| probes.liveness.periodSeconds | int | `5` |  |
| probes.readiness.failureThreshold | int | `6` |  |
| probes.readiness.httpGet.path | string | `"/probe"` |  |
| probes.readiness.httpGet.port | string | `"http"` |  |
| probes.readiness.initialDelaySeconds | int | `10` |  |
| probes.readiness.periodSeconds | int | `5` |  |
| probes.startup.failureThreshold | int | `30` |  |
| probes.startup.httpGet.path | string | `"/probe"` |  |
| probes.startup.httpGet.port | string | `"http"` |  |
| probes.startup.initialDelaySeconds | int | `10` |  |
| probes.startup.periodSeconds | int | `10` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.alert | string | `"ConfluenceConnectorUniqueAPIErrors"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.annotations.description | string | `"The Confluence Connector is experiencing Unique REST API errors (4xx/5xx responses). Current error rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes (both the connector and the Unique Services)\n3. Verify network connectivity between connector and Unique Services\n4. Verify service user settings and permissions within Unique\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.annotations.summary | string | `"Confluence Connector Unique REST API errors detected"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.expr | string | `"(\n  sum(rate(cfc_unique_rest_api_request_duration_seconds_count{http_status_class=~\"4xx|5xx\"}[5m]))\n  /\n  sum(rate(cfc_unique_rest_api_request_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.for | string | `"30s"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.labels.alertGroup | string | `"confluence-connector"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.labels.severity | string | `"warning"` |  |
| proxyConfig | object | `{"authMode":"none","enabled":true}` | HTTP proxy configuration for external API calls Required for environments where internet access is only available through a proxy. Users preferring setting all variables by hand disable the enabled flag and remove confluence-connector-proxy-config from extraEnvCM. |
| proxyConfig.authMode | string | `"none"` | Proxy authentication mode none: proxy disabled no_auth: proxy enabled, no authentication username_password: username/password authentication ssl_tls: TLS client certificate authentication |
| proxyConfig.enabled | bool | `true` | if disabled, confluence-connector-proxy-config must be removed from extraEnvCM. |
| resources.limits.memory | string | `"1Gi"` |  |
| resources.requests.cpu | int | `1` |  |
| resources.requests.memory | string | `"512Mi"` |  |
| routes.hostname | string | `""` |  |
| selectorComponentLabel | string | `"server"` |  |
| service.enabled | bool | `false` |  |
| serviceAccount.enabled | bool | `true` |  |
| volumeMounts[0].mountPath | string | `"/tmp"` |  |
| volumeMounts[0].name | string | `"tmp"` |  |
| volumes[0].emptyDir | object | `{}` |  |
| volumes[0].name | string | `"tmp"` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
