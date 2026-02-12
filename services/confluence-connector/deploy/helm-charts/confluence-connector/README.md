# confluence-connector

Take content from Confluence and send it to Unique AI for RAG ingestion.

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/unique-ag/helm-charts | connector(backend-service) | ~10.1.0 |

## Installation

### Requirements

You need to install [`aslafy-z/helm-git`](https://github.com/aslafy-z/helm-git). OCI registry based installation options will be provided in a future release.

### Helm

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```bash
helm repo add cfc git+https://github.com/Unique-AG/connectors@services/confluence-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
helm template cfc/confluence-connector --version <v-less-version-only>
```

### [`helmfile`](https://helmfile.readthedocs.io)

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```yaml
# helmfile version v1.1.7
repositories:
  - name: cfc
    url: git+https://github.com/Unique-AG/connectors@services/confluence-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
releases:
  - name: confluence-connector
    chart: cfc/confluence-connector
    version: <v-less-version-only>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)
```yaml
spec:
  name: confluence-connector
  …
  sources:
    - repoURL: https://github.com/Unique-AG/connectors.git
      path: services/confluence-connector/deploy/helm-charts/confluence-connector
      targetRevision: <release-tag>
```

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| alerts | object | `{"defaultAlerts":{"additionalLabels":{},"uniqueApi":{"customRules":{},"disabled":{},"enabled":true}},"enabled":false}` | Prometheus alerting rules configuration |
| alerts.defaultAlerts | object | `{"additionalLabels":{},"uniqueApi":{"customRules":{},"disabled":{},"enabled":true}}` | Default alert definitions |
| alerts.defaultAlerts.additionalLabels | object | `{}` | Additional labels to add to all default alerts |
| alerts.defaultAlerts.uniqueApi | object | `{"customRules":{},"disabled":{},"enabled":true}` | Enable Unique REST API error rate alerts |
| alerts.defaultAlerts.uniqueApi.customRules | object | `{}` | Override alert rules with custom values (for duration, severity, threshold, etc.) |
| alerts.defaultAlerts.uniqueApi.disabled | object | `{}` | Disable specific alerts by setting them to true |
| alerts.enabled | bool | `false` | Enable PrometheusRule resource creation |
| connector.deployment.metadata.annotations."reloader.stakater.com/auto" | string | `"true"` |  |
| connector.env.LOGS_DIAGNOSTICS_DATA_POLICY | string | `"conceal"` |  |
| connector.env.LOG_LEVEL | string | `"info"` |  |
| connector.env.MAX_FILE_SIZE_BYTES | string | `"209715200"` |  |
| connector.env.MAX_HEAP_MB | int | `896` |  |
| connector.env.NODE_ENV | string | `"production"` |  |
| connector.env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| connector.env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"51350"` |  |
| connector.env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| connector.env.TENANT_CONFIG_PATH_PATTERN | string | `"/app/tenant-configs/*-tenant-config.yaml"` |  |
| connector.envVars | list | `[]` | Environment variables from secrets. Example for loading secrets (uncomment and customize as needed):   envVars:     # For Zitadel authentication (required when authMode is 'external')     - name: ZITADEL_CLIENT_SECRET       valueFrom:         secretKeyRef:           name: confluence-connector-secret           key: ZITADEL_CLIENT_SECRET     # For Confluence OAuth 2.0 (2LO) client secret     - name: CONFLUENCE_CLIENT_SECRET       valueFrom:         secretKeyRef:           name: confluence-connector-secret           key: CONFLUENCE_CLIENT_SECRET See https://artifacthub.io/packages/helm/unique/backend-service?modal=values&path=envVars for more options. |
| connector.extraEnvCM | list | `[]` | List of ConfigMaps to load as environment variables |
| connector.image.repository | string | `"ghcr.io/unique-ag/connectors/services/confluence-connector"` |  |
| connector.image.tag | string | `"2.0.0-alpha.0"` |  |
| connector.ports.application | int | `51349` |  |
| connector.ports.metrics | int | `51350` |  |
| connector.resources.limits.memory | string | `"1024Mi"` |  |
| connector.resources.requests.cpu | string | `"500m"` |  |
| connector.resources.requests.memory | string | `"960Mi"` |  |
| connector.routes.paths.default.enabled | bool | `false` |  |
| connector.service.enabled | bool | `false` |  |
| connector.serviceAccount.enabled | bool | `true` |  |
| connector.volumeMounts[0].mountPath | string | `"/tmp"` |  |
| connector.volumeMounts[0].name | string | `"tmp"` |  |
| connector.volumeMounts[1] | object | `{"mountPath":"/app/tenant-configs","name":"tenant-config","readOnly":true}` | Mount tenant configuration directory |
| connector.volumes[0].emptyDir | object | `{}` |  |
| connector.volumes[0].name | string | `"tmp"` |  |
| connector.volumes[1] | object | `{"configMap":{"name":"confluence-connector-tenant-config"},"name":"tenant-config"}` | Tenant configuration YAML file mounted from ConfigMap |
| connectorConfig.enabled | bool | `true` | if disabled, tenant-config must be removed from the connector.volumes and connector.volumeMounts |
| connectorConfig.tenants[0].confluence.apiRateLimitPerMinute | int | `100` | Number of Confluence API requests allowed per minute |
| connectorConfig.tenants[0].confluence.auth.clientId | string | `"unset_default_value"` | OAuth 2.0 (2LO) application client ID |
| connectorConfig.tenants[0].confluence.auth.mode | string | `"oauth_2lo"` | authentication mode possible values: oauth_2lo |
| connectorConfig.tenants[0].confluence.baseUrl | string | `"unset_default_value"` | base url of the Confluence instance example (cloud): https://acme.atlassian.net/wiki example (data-center): https://confluence.acme.com |
| connectorConfig.tenants[0].confluence.ingestAllLabel | string | `"ai-ingest-all"` | Label to trigger full sync of all labeled pages |
| connectorConfig.tenants[0].confluence.ingestSingleLabel | string | `"ai-ingest"` | Label to trigger single-page sync |
| connectorConfig.tenants[0].confluence.instanceType | string | `"cloud"` | Confluence instance type: cloud or data-center |
| connectorConfig.tenants[0].name | string | `"default"` |  |
| connectorConfig.tenants[0].processing.concurrency | int | `1` | how many pages you want to submit for ingestion into Unique at once |
| connectorConfig.tenants[0].processing.scanIntervalCron | string | `"*/15 * * * *"` | cron expression for the scheduled Confluence scan interval default: every 15 minutes |
| connectorConfig.tenants[0].processing.stepTimeoutSeconds | int | `300` | timeout in seconds for a page processing step before it will stop and skip processing the page |
| connectorConfig.tenants[0].unique.apiRateLimitPerMinute | int | `100` | Number of Unique API requests allowed per minute |
| connectorConfig.tenants[0].unique.authMode | string | `"cluster_local"` | communication mode for the Unique Services possible values: cluster_local, external cluster_local: communicates using in-cluster URLs and requires serviceExtraHeaders with x-company-id and x-user-id external: communicates using external URLs and requires authentication via Zitadel |
| connectorConfig.tenants[0].unique.ingestionServiceBaseUrl | string | `"unset_default_value"` | base URL for the ingestion service example: https://api.unique.app/ingestion example: http://node-ingestion.finance-gpt:8091 |
| connectorConfig.tenants[0].unique.scopeManagementServiceBaseUrl | string | `"unset_default_value"` | base URL for the scope management service example: https://api.unique.app/scope-management example: http://node-scope-management.finance-gpt:8094 |
| connectorConfig.tenants[0].unique.serviceExtraHeaders | object | `{"x-company-id":"unset_default_value","x-user-id":"unset_default_value"}` | Object containing extra HTTP headers for Unique API requests (GraphQL and REST) Required when authMode is cluster_local. Must contain x-company-id and x-user-id headers. example: {"x-company-id": "1234567890", "x-user-id": "1234567890"} |
| connectorConfig.tenants[0].unique.zitadel | object | `{"clientId":"unset_default_value","oauthTokenUrl":"unset_default_value","projectId":"unset_default_value"}` | Zitadel authentication configuration (required when authMode is external) |
| connectorConfig.tenants[0].unique.zitadel.clientId | string | `"unset_default_value"` | Zitadel client ID |
| connectorConfig.tenants[0].unique.zitadel.oauthTokenUrl | string | `"unset_default_value"` | Zitadel OAuth token URL example: https://idp.unique.app/oauth/v2/token |
| connectorConfig.tenants[0].unique.zitadel.projectId | string | `"unset_default_value"` | Zitadel project ID example: 225317577440629999 |
| grafana | object | `{"dashboard":{"enabled":false,"folder":"connectors"}}` | Grafana dashboard configuration |
| grafana.dashboard.enabled | bool | `false` | Enable Grafana dashboard ConfigMap creation |
| grafana.dashboard.folder | string | `"connectors"` | Grafana folder where the dashboard will be placed |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
