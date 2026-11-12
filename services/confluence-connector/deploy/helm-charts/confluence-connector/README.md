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
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.alert | string | `"ConfluenceConnectorContentFailures"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.annotations.description | string | `"Tenant {{ $labels.tenant }} syncs complete, but pages, attachments or deletions keep failing. {{ $value }} failures in the last 2 hours."` |  |
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.annotations.runbook | string | `"1. Search the connector logs for \"Failed to\" with this tenantName\n2. Check the failing items in the \"Page ingestion summary\" and \"Attachment ingestion summary\" log lines\n3. Unique ingestion errors also show in ConfluenceConnectorUniqueAPIErrors\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.annotations.summary | string | `"Confluence Connector cannot ingest or delete content for tenant {{ $labels.tenant }}"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.expr | string | `"(\n  sum by (namespace, tenant) (increase(cfc_pages_processed_total{result=\"failure\"}[2h]))\n  + sum by (namespace, tenant) (increase(cfc_attachments_processed_total{result=\"failure\"}[2h]))\n  + sum by (namespace, tenant) (increase(cfc_content_deleted_total{result=\"failure\"}[2h]))\n) > 0\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.for | string | `"3h"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.labels.alertGroup | string | `"confluence-connector"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorContentFailures.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.alert | string | `"ConfluenceConnectorSyncDegraded"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.annotations.description | string | `"More than half of the syncs of tenant {{ $labels.tenant }} in the last 6 hours failed, but some succeeded. Current failure ratio: {{ humanizePercentage $value }}."` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.annotations.runbook | string | `"1. Search the connector logs for \"Sync failed\" with this tenantName\n2. Intermittent failures usually come from timeouts or rate limits on the Confluence or Unique side\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.annotations.summary | string | `"Confluence Connector sync degraded for tenant {{ $labels.tenant }}"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.expr | string | `"(\n  sum by (namespace, tenant) (increase(cfc_syncs_total{result=\"failure\"}[6h]))\n  /\n  sum by (namespace, tenant) (increase(cfc_syncs_total[6h]))\n) > 0.5\nunless on (namespace, tenant)\n(\n  sum by (namespace, tenant) (increase(cfc_syncs_total{result=\"success\"}[3h])) == 0\n)\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.for | string | `"15m"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.labels.alertGroup | string | `"confluence-connector"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncDegraded.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.alert | string | `"ConfluenceConnectorSyncFailing"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.annotations.description | string | `"Every sync of tenant {{ $labels.tenant }} in the last 3 hours failed. Nothing new from Confluence reaches Unique."` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.annotations.runbook | string | `"1. Search the connector logs for \"Sync failed\" with this tenantName\n2. \"Scope with id ... not found\": the root folder in Unique was deleted. Create a new one and update ingestion.scopeId\n3. \"Root scope ownership mismatch\" or \"Failed to claim root scope ownership\": another Confluence instance owns the folder\n4. 401/403 from Confluence or Zitadel: rotate the client secret\n5. Network errors: check NetworkPolicy, proxy and DNS\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.annotations.summary | string | `"Confluence Connector sync failing for tenant {{ $labels.tenant }}"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.expr | string | `"(\n  sum by (namespace, tenant) (increase(cfc_syncs_total{result=\"failure\"}[3h])) > 0\n)\nand on (namespace, tenant)\n(\n  sum by (namespace, tenant) (increase(cfc_syncs_total[3h])) > 1.5\n)\nunless on (namespace, tenant)\n(\n  sum by (namespace, tenant) (increase(cfc_syncs_total{result=\"success\"}[3h])) > 0\n)\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.for | string | `"15m"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.labels.alertGroup | string | `"confluence-connector"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncFailing.labels.severity | string | `"critical"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.alert | string | `"ConfluenceConnectorSyncStuck"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.annotations.description | string | `"A sync of tenant {{ $labels.tenant }} started more than 6 hours ago and has not finished. While a sync runs, every scheduled sync of the tenant is skipped."` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.annotations.runbook | string | `"1. Check the connector logs for the last progress line of this tenant\n2. A very large first sync can take this long. Check whether pages are still being ingested\n3. If nothing moves, restart the pod\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.annotations.summary | string | `"Confluence Connector sync of tenant {{ $labels.tenant }} has not finished for 6 hours"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.expr | string | `"max by (namespace, tenant) (cfc_sync_phase{phase!=\"idle\"}) == 1\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.for | string | `"6h"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.labels.alertGroup | string | `"confluence-connector"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorSyncStuck.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.alert | string | `"ConfluenceConnectorTenantCleanupFailing"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.annotations.description | string | `"Tenant {{ $labels.tenant }} has status deleted, and every cleanup in the last 3 hours failed. Its content stays in Unique."` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.annotations.runbook | string | `"1. Search the connector logs for \"cleanup\" with this tenantName\n2. Check that the service user can still manage the tenant's root folder\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.annotations.summary | string | `"Confluence Connector cannot clean up deleted tenant {{ $labels.tenant }}"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.expr | string | `"(\n  sum by (namespace, tenant) (increase(cfc_tenant_cleanups_total{result=\"failure\"}[3h])) > 0\n)\nand on (namespace, tenant)\n(\n  sum by (namespace, tenant) (increase(cfc_tenant_cleanups_total[3h])) > 1.5\n)\nunless on (namespace, tenant)\n(\n  sum by (namespace, tenant) (increase(cfc_tenant_cleanups_total{result=\"success\"}[3h])) > 0\n)\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.for | string | `"15m"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.labels.alertGroup | string | `"confluence-connector"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorTenantCleanupFailing.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.alert | string | `"ConfluenceConnectorUniqueAPIErrors"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.annotations.description | string | `"More than 1% of the Confluence Connector's requests to the Unique API (GraphQL and REST) failed in the last 75 minutes. Current error rate: {{ humanizePercentage $value }}."` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes (both the connector and the Unique Services)\n3. Verify network connectivity between connector and Unique Services\n4. Verify service user settings and permissions within Unique\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.annotations.summary | string | `"Confluence Connector Unique API errors detected"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.expr | string | `"sum by (namespace) (increase(confluence_connector_unique_api_requests_total{result=\"error\"}[75m]))\n/\nsum by (namespace) (increase(confluence_connector_unique_api_requests_total[75m]))\n> 0.01\n"` |  |
| prometheus.additionalAlerts.ConfluenceConnectorUniqueAPIErrors.for | string | `"5m"` |  |
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

