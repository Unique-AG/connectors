# sharepoint-connector

Take content from SharePoint and send it to Unique AI for RAG ingestion.

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/unique-ag/helm-charts | connector(backend-service) | ~6.1.0 |

## Installation

Until `2.0.0`, the chart can only be installed via

### Requirements

You need to install [`aslafy-z/helm-git`](https://github.com/aslafy-z/helm-git). OCI registry based installation options will be provided with `2.0.0` onwards.

### Helm

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```bash
helm repo add spc git+https://github.com/Unique-AG/connectors@services/sharepoint-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
helm template spc/sharepoint-connector --version <v-less-version-only>
```

### [`helmfile`](https://helmfile.readthedocs.io)

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```yaml
# helmfile version v1.1.7
repositories:
  - name: spc
    url: git+https://github.com/Unique-AG/connectors@services/sharepoint-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
releases:
  - name: sharepoint-connector
    chart: spc/sharepoint-connector
    version: <v-less-version-only>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)
```yaml
spec:
  name: sharepoint-connector
  …
  sources:
    - repoURL: https://github.com/Unique-AG/connectors.git
      path: services/sharepoint-connector/deploy/helm-charts/sharepoint-connector
      targetRevision: <release-tag>
```

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| alerts | object | `{"defaultAlerts":{"additionalLabels":{},"graphql":{"customRules":{},"disabled":{},"enabled":true},"uniqueApi":{"customRules":{},"disabled":{},"enabled":true}},"enabled":false}` | Prometheus alerting rules configuration |
| alerts.defaultAlerts | object | `{"additionalLabels":{},"graphql":{"customRules":{},"disabled":{},"enabled":true},"uniqueApi":{"customRules":{},"disabled":{},"enabled":true}}` | Default alert definitions |
| alerts.defaultAlerts.additionalLabels | object | `{}` | Additional labels to add to all default alerts |
| alerts.defaultAlerts.graphql | object | `{"customRules":{},"disabled":{},"enabled":true}` | Enable GraphQL API error rate alerts |
| alerts.defaultAlerts.graphql.customRules | object | `{}` | Override alert rules with custom values (for duration, severity, threshold, etc.) |
| alerts.defaultAlerts.graphql.disabled | object | `{}` | Disable specific alerts by setting them to true |
| alerts.defaultAlerts.uniqueApi | object | `{"customRules":{},"disabled":{},"enabled":true}` | Enable Unique REST API error rate alerts |
| alerts.defaultAlerts.uniqueApi.customRules | object | `{}` | Override alert rules with custom values (for duration, severity, threshold, etc.) |
| alerts.defaultAlerts.uniqueApi.disabled | object | `{}` | Disable specific alerts by setting them to true |
| alerts.enabled | bool | `false` | Enable PrometheusRule resource creation |
| connector.deployment.metadata.annotations."reloader.stakater.com/auto" | string | `"true"` |  |
| connector.env.LOGS_DIAGNOSTICS_DATA_POLICY | string | `"conceal"` |  |
| connector.env.LOG_LEVEL | string | `"info"` |  |
| connector.env.MAX_FILE_SIZE_BYTES | string | `"209715200"` |  |
| connector.env.MAX_HEAP_MB | int | `1920` |  |
| connector.env.NODE_ENV | string | `"production"` |  |
| connector.env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| connector.env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"51346"` |  |
| connector.env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| connector.envVars | list | `[]` | Environment variables from secrets. Required when authMode is 'external'. When using external authMode, add UNIQUE_ZITADEL_CLIENT_SECRET from a secret. See https://artifacthub.io/packages/helm/unique/backend-service?modal=values&path=envVars for more options. |
| connector.extraEnvCM[0] | string | `"sharepoint-connector-config"` |  |
| connector.image.repository | string | `"ghcr.io/unique-ag/connectors/services/sharepoint-connector"` |  |
| connector.image.tag | string | `"2.0.0-beta.3"` |  |
| connector.networkPolicy.egress | string | `nil` |  |
| connector.networkPolicy.enabled | bool | `true` |  |
| connector.networkPolicy.policyTypes[0] | string | `"Ingress"` |  |
| connector.ports.application | int | `51345` |  |
| connector.ports.metrics | int | `51346` |  |
| connector.resources.limits.memory | string | `"2048Mi"` |  |
| connector.resources.requests.cpu | int | `1` |  |
| connector.resources.requests.memory | string | `"1984Mi"` |  |
| connector.routes.paths.default.enabled | bool | `false` |  |
| connector.service.enabled | bool | `false` |  |
| connector.serviceAccount.enabled | bool | `true` |  |
| connector.serviceAccount.workloadIdentity.clientId | string | `"unset_default_value"` |  |
| connector.serviceAccount.workloadIdentity.enabled | bool | `true` |  |
| connector.volumeMounts[0].mountPath | string | `"/tmp"` |  |
| connector.volumeMounts[0].name | string | `"tmp"` |  |
| connector.volumeMounts[1].mountPath | string | `"/app/key.pem"` |  |
| connector.volumeMounts[1].name | string | `"sharepoint-connector-secret"` |  |
| connector.volumeMounts[1].readOnly | bool | `true` |  |
| connector.volumeMounts[1].subPath | string | `"key.pem"` |  |
| connector.volumes[0].emptyDir | object | `{}` |  |
| connector.volumes[0].name | string | `"tmp"` |  |
| connector.volumes[1].name | string | `"sharepoint-connector-secret"` |  |
| connector.volumes[1].secret.items[0].key | string | `"key.pem"` |  |
| connector.volumes[1].secret.items[0].path | string | `"key.pem"` |  |
| connector.volumes[1].secret.secretName | string | `"sharepoint-connector-secret"` |  |
| connectorConfig | object | `{"enabled":true,"processing":{"allowedMimeTypes":["application/pdf","text/plain","text/html","application/x-asp","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.ms-excel","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.openxmlformats-officedocument.presentationml.presentation"],"concurrency":1,"maxFileSizeBytes":null,"scanIntervalCron":"*/15 * * * *","stepTimeoutSeconds":300,"syncMode":"content_only"},"sharepoint":{"auth":{"clientId":null,"mode":"certificate","privateKeyPassword":null,"privateKeyPath":"/app/key.pem","tenantId":"unset_default_value","thumbprintSha1":null,"thumbprintSha256":null},"baseUrl":"unset_default_value","graph":{"apiRateLimitPerMinute":780000},"siteIds":["00000000-0000-0000-0000-000000000000","00000000-0000-0000-0000-000000000001"],"syncColumnName":"unset_default_value"},"unique":{"apiRateLimitPerMinute":100,"authMode":"cluster_local","ingestionMode":"recursive","ingestionServiceBaseUrl":"unset_default_value","inheritModes":[],"maxIngestedFiles":1000,"scopeId":"unset_default_value","scopeManagementServiceBaseUrl":"unset_default_value","serviceExtraHeaders":{"x-company-id":"unset_default_value","x-user-id":"unset_default_value"},"storeInternally":"disabled","zitadel":{"clientId":"unset_default_value","oauthTokenUrl":"unset_default_value","projectId":"unset_default_value"}}}` | config for the deployed connector, will be mapped to the connectors environment variables users preferring setting all variables by hand disable the enabled flag and set the extraEnvCM to [] |
| connectorConfig.enabled | bool | `true` | if disabled, connector.extraEnvCM must be set to [] |
| connectorConfig.processing.allowedMimeTypes | list | `["application/pdf","text/plain","text/html","application/x-asp","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.ms-excel","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.openxmlformats-officedocument.presentationml.presentation"]` | list of allowed MIME types for files to sync |
| connectorConfig.processing.concurrency | int | `1` | how many files you want to submit for ingestion into Unique at once |
| connectorConfig.processing.scanIntervalCron | string | `"*/15 * * * *"` | cron expression for the scheduled SharePoint scan interval default: every 15 minutes |
| connectorConfig.processing.stepTimeoutSeconds | int | `300` | timeout in seconds for a file processing step before it will stop and skip processing the file |
| connectorConfig.processing.syncMode | string | `"content_only"` | mode of synchronization from SharePoint to Unique. Possible values: - content_only: sync only the content, - content_and_permissions: sync both content and permissions, |
| connectorConfig.sharepoint.auth.privateKeyPath | string | `"/app/key.pem"` | path to the private key file of the Azure AD application certificate in PEM format this closely relates to the volumeMounts and volume definitions in the connector section users wanting to use another path can override this value and unset the volumeMounts and volume definitions |
| connectorConfig.sharepoint.auth.tenantId | string | `"unset_default_value"` | tenant id against which the graph api calls are made example: 12345678-1234-1234-1234-123456789012 |
| connectorConfig.sharepoint.baseUrl | string | `"unset_default_value"` | base url of the sharepoint instance example: https://acme.sharepoint.com |
| connectorConfig.sharepoint.siteIds | list | `["00000000-0000-0000-0000-000000000000","00000000-0000-0000-0000-000000000001"]` | Array of site IDs to scan |
| connectorConfig.sharepoint.syncColumnName | string | `"unset_default_value"` | column name against which the files are synced example: FinanceGPTKnowledge |
| connectorConfig.unique.apiRateLimitPerMinute | int | `100` | Number of Unique API requests allowed per minute |
| connectorConfig.unique.authMode | string | `"cluster_local"` | communication mode for the Unique Services possible values: cluster_local, external cluster_local: communicates using in-cluster URLs and requires serviceExtraHeaders with x-company-id and x-user-id external: communicates using external URLs and requires authentication via Zitadel |
| connectorConfig.unique.ingestionMode | string | `"recursive"` | ingestion mode: flat ingests all files to a single root scope, recursive maintains the folder hierarchy (path-based ingestion) possible values: flat, recursive |
| connectorConfig.unique.ingestionServiceBaseUrl | string | `"unset_default_value"` | base URL for the ingestion service example: https://api.unique.app/ingestion example: http://node-ingestion.finance-gpt:8091 |
| connectorConfig.unique.maxIngestedFiles | int | `1000` | Maximum number of files to ingest per site in a single run. If the number of new + updated files for a site exceeds this limit, the sync for that site will fail. |
| connectorConfig.unique.scopeId | string | `"unset_default_value"` | Scope ID to be used as root for ingestion. Required for both flat and recursive modes. example: scope_bu4gokr0atzj0kfiuaaaaaaa |
| connectorConfig.unique.scopeManagementServiceBaseUrl | string | `"unset_default_value"` | base URL for the scope management service example: https://api.unique.app/scope-management example: http://node-scope-management.finance-gpt:8094 |
| connectorConfig.unique.inheritModes | list | `[]` | List of inheritance options for scopes and files in content_only mode. Allowed values: none, inherit_scopes, inherit_files. When empty or unset, both scopes and files inherit in content_only; ignored in content_and_permissions. |
| connectorConfig.unique.serviceExtraHeaders | object | `{"x-company-id":"unset_default_value","x-user-id":"unset_default_value"}` | Object containing extra HTTP headers for Unique API requests (GraphQL and REST) Required when authMode is cluster_local. Must contain x-company-id and x-user-id headers. example: {"x-company-id": "1234567890", "x-user-id": "1234567890"} |
| connectorConfig.unique.storeInternally | string | `"disabled"` | Whether to store content internally in Unique or not. possible values: enabled, disabled |
| connectorConfig.unique.zitadel | object | `{"clientId":"unset_default_value","oauthTokenUrl":"unset_default_value","projectId":"unset_default_value"}` | Zitadel authentication configuration (required when authMode is external) |
| connectorConfig.unique.zitadel.clientId | string | `"unset_default_value"` | Zitadel client ID |
| connectorConfig.unique.zitadel.oauthTokenUrl | string | `"unset_default_value"` | Zitadel OAuth token URL example: https://idp.unique.app/oauth/v2/token |
| connectorConfig.unique.zitadel.projectId | string | `"unset_default_value"` | Zitadel project ID example: 225317577440629999 |
| grafana | object | `{"dashboard":{"enabled":false,"folder":"connectors"}}` | Grafana dashboard configuration |
| grafana.dashboard.enabled | bool | `false` | Enable Grafana dashboard ConfigMap creation |
| grafana.dashboard.folder | string | `"connectors"` | Grafana folder where the dashboard will be placed |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
