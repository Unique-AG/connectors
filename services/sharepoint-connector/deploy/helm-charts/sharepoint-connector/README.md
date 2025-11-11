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
| connector.deployment.metadata.annotations."reloader.stakater.com/auto" | string | `"true"` |  |
| connector.env.LOG_LEVEL | string | `"info"` |  |
| connector.env.MAX_FILE_SIZE_BYTES | string | `"209715200"` |  |
| connector.env.MAX_HEAP_MB | int | `1920` |  |
| connector.env.NODE_ENV | string | `"production"` |  |
| connector.env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| connector.env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"51346"` |  |
| connector.env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| connector.envVars[0] | object | `{"name":"UNIQUE_ZITADEL_CLIENT_SECRET","valueFrom":{"secretKeyRef":{"key":"UNIQUE_ZITADEL_CLIENT_SECRET","name":"sharepoint-connector-secret"}}}` | loading of Zitadel Secret, Users can supersede this with their own secret that contains UNIQUE_ZITADEL_CLIENT_SECRET or use https://artifacthub.io/packages/helm/unique/backend-service?modal=values&path=envVars to load completely arbitrary secret mappings. See also below in connectorConfig.unique.zitadel.clientSecret. |
| connector.extraEnvCM[0] | string | `"sharepoint-connector-config"` |  |
| connector.image.repository | string | `"ghcr.io/unique-ag/connectors/services/sharepoint-connector"` |  |
| connector.image.tag | string | `"2.0.0-alpha.11"` |  |
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
| connectorConfig | object | `{"enabled":true,"processing":{"allowedMimeTypes":["application/pdf","text/plain","text/html","application/x-asp","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.ms-excel","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.openxmlformats-officedocument.presentationml.presentation"],"concurrency":1,"maxFileSizeBytes":null,"scanIntervalCron":"*/15 * * * *","stepTimeoutSeconds":300},"sharepoint":{"auth":{"clientId":null,"mode":"certificate","privateKeyPassword":null,"privateKeyPath":"/app/key.pem","tenantId":"unset_default_value","thumbprintSha1":null,"thumbprintSha256":null},"baseUrl":"unset_default_value","graph":{"apiRateLimitPerMinute":780000},"siteIds":["00000000-0000-0000-0000-000000000000","00000000-0000-0000-0000-000000000001"],"syncColumnName":"unset_default_value"},"unique":{"apiRateLimitPerMinute":100,"authMode":"cluster_local","fileDiffUrl":"unset_default_value","ingestionGraphqlUrl":"unset_default_value","ingestionMode":"recursive","rootScopeName":null,"scopeId":null,"scopeManagementGraphqlUrl":"unset_default_value","serviceExtraHeaders":{},"zitadel":{"clientId":"unset_default_value","oauthTokenUrl":"unset_default_value","projectId":"unset_default_value","serviceExtraHeaders":{}}}}` | config for the deployed connector, will be mapped to the connectors environment variables users preferring setting all variables by hand disable the enabled flag and set the extraEnvCM to [] |
| connectorConfig.enabled | bool | `true` | if disabled, connector.extraEnvCM must be set to [] |
| connectorConfig.processing.scanIntervalCron | string | `"*/15 * * * *"` | cron expression for the scheduled SharePoint scan interval default: every 15 minutes |
| connectorConfig.sharepoint.auth.privateKeyPath | string | `"/app/key.pem"` | path to the private key file of the Azure AD application certificate in PEM format this closely relates to the volumeMounts and volume definitions in the connector section users wanting to use another path can override this value and unset the volumeMounts and volume definitions |
| connectorConfig.sharepoint.auth.tenantId | string | `"unset_default_value"` | tenant id against which the graph api calls are made example: 12345678-1234-1234-1234-123456789012 |
| connectorConfig.sharepoint.baseUrl | string | `"unset_default_value"` | base url of the sharepoint instance example: https://acme.sharepoint.com |
| connectorConfig.sharepoint.siteIds | list | `["00000000-0000-0000-0000-000000000000","00000000-0000-0000-0000-000000000001"]` | Array of site IDs to scan |
| connectorConfig.sharepoint.syncColumnName | string | `"unset_default_value"` | column name against which the files are synced example: FinanceGPTKnowledge |
| connectorConfig.unique.authMode | string | `"cluster_local"` | communication mode for the Unique Services possible values: cluster_local, external cluster_local: comunicates using in-cluster URLs and requires no authentication external: communicates using external URLs and requires authentication via Zitadel |
| connectorConfig.unique.fileDiffUrl | string | `"unset_default_value"` | url for the file diff example: https://api.unique.app/ingestion/v1/content/file-diff |
| connectorConfig.unique.ingestionGraphqlUrl | string | `"unset_default_value"` | url for the ingestion graphql TODO: should use only public urls! example: https://api.unique.app/ingestion/graphql |
| connectorConfig.unique.rootScopeName | string | `nil` | name of the root scope/folder in the knowledge base where SharePoint content should be synced example: SharePoint Content |
| connectorConfig.unique.scopeId | string | `nil` | scope id for the scope based ingestion example: scope_bu4gokr0atzj0kfiuaaaaaaa |
| connectorConfig.unique.scopeManagementGraphqlUrl | string | `"unset_default_value"` | url for the scope management graphql |
| connectorConfig.unique.serviceExtraHeaders | object | `{}` | Object containing extra HTTP headers for ingestion API requests (GraphQL and file diff) Used for service-to-service authentication when using internal cluster URLs |
| connectorConfig.unique.zitadel.projectId | string | `"unset_default_value"` | project id for the zitadel project example: 225317577440629999 |
| connectorConfig.unique.zitadel.serviceExtraHeaders | object | `{}` | Object containing extra HTTP headers for Zitadel OAuth requests |
| grafana.dashboard.enabled | bool | `false` |  |
| grafana.dashboard.folder | string | `"connectors"` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
