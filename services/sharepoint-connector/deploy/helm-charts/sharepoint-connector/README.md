# sharepoint-connector

Take content from SharePoint and send it to Unique AI for RAG ingestion.

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/unique-ag/helm | base | 0.1.0-4c70c3 |

## Installation

Use OCI charts only. Prefer `getunique.azurecr.io`; `uniquecr.azurecr.io` is private and kept for consistency, and GHCR is maintained best-effort.

- `oci://getunique.azurecr.io/helm/sharepoint-connector`
- `oci://uniquecr.azurecr.io/connectors/helm/sharepoint-connector`
- `oci://ghcr.io/unique-ag/connectors/helm/sharepoint-connector`

### Helm

```bash
helm template sharepoint-connector \
  oci://getunique.azurecr.io/helm/sharepoint-connector \
  --version <version>
```

### [`helmfile`](https://helmfile.readthedocs.io)

```yaml
# helmfile version v1.1.7
releases:
  - name: sharepoint-connector
    chart: oci://getunique.azurecr.io/helm/sharepoint-connector
    version: <version>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)

Pin the chart by OCI digest in GitOps. Keep the version as a comment for humans.

```yaml
spec:
  name: sharepoint-connector
  sources:
    - repoURL: oci://getunique.azurecr.io/helm/sharepoint-connector
      path: .
      targetRevision: sha256:<chart-digest> # <version>
```

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| connectorConfig | object | `{"enabled":true,"processing":{"allowedMimeTypes":["application/pdf","text/plain","text/html","application/x-asp","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.ms-excel","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.openxmlformats-officedocument.presentationml.presentation","text/csv"],"concurrency":1,"maxFileSizeToIngestBytes":null,"mimeTypeOverridesByExtension":{".csv":"text/csv"},"scanIntervalCron":"*/15 * * * *","stepTimeoutSeconds":300},"sharepoint":{"apiRateLimitPerMinuteThousands":780,"auth":{"clientId":"{{ fail \"connectorConfig.sharepoint.auth.clientId is mandatory when auth.mode is certificate. Override in your deployment values.\" }}","mode":"certificate","privateKeyPath":"/app/key.pem","thumbprintSha1":"","thumbprintSha256":""},"baseUrl":"{{ fail \"connectorConfig.sharepoint.baseUrl is mandatory. Override in your deployment values.\" }}","siteDefaults":{},"sitesSource":"config_file","tenantId":"{{ fail \"connectorConfig.sharepoint.tenantId is mandatory. Override in your deployment values.\" }}"},"unique":{"apiRateLimitPerMinute":100,"authMode":"cluster_local","ingestionServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}","scopeManagementServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}","serviceExtraHeaders":{"x-company-id":"{{ fail \"connectorConfig.unique.serviceExtraHeaders.x-company-id is mandatory when authMode is cluster_local. Override in your deployment values.\" }}","x-user-id":"{{ fail \"connectorConfig.unique.serviceExtraHeaders.x-user-id is mandatory when authMode is cluster_local. Override in your deployment values.\" }}"},"zitadel":{"clientId":"{{ fail \"connectorConfig.unique.zitadel.clientId is mandatory when authMode is external. Override in your deployment values.\" }}","oauthTokenUrl":"{{ fail \"connectorConfig.unique.zitadel.oauthTokenUrl is mandatory when authMode is external. Override in your deployment values.\" }}","projectId":"{{ fail \"connectorConfig.unique.zitadel.projectId is mandatory when authMode is external. Override in your deployment values.\" }}"}}}` | Config for the deployed connector, will be mapped to the connectors environment variables. Users preferring setting all variables on their own disable the enabled flag and remove the tenant-config from volumes and volumeMounts. |
| connectorConfig.enabled | bool | `true` | if disabled, tenant-config must be removed from volumes and volumeMounts |
| connectorConfig.processing.allowedMimeTypes | list | `["application/pdf","text/plain","text/html","application/x-asp","application/vnd.openxmlformats-officedocument.wordprocessingml.document","application/vnd.ms-excel","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","application/vnd.openxmlformats-officedocument.presentationml.presentation","text/csv"]` | list of allowed MIME types for files to sync |
| connectorConfig.processing.concurrency | int | `1` | how many files you want to submit for ingestion into Unique at once |
| connectorConfig.processing.mimeTypeOverridesByExtension | object | `{".csv":"text/csv"}` | map of file extension suffix to canonical MIME type, used to override the SharePoint-reported mimeType. User-supplied values replace the default wholesale; include `.csv` in custom maps to retain the CSV fix |
| connectorConfig.processing.scanIntervalCron | string | `"*/15 * * * *"` | cron expression for the scheduled SharePoint scan interval default: every 15 minutes |
| connectorConfig.processing.stepTimeoutSeconds | int | `300` | timeout in seconds for a file processing step before it will stop and skip processing the file |
| connectorConfig.sharepoint.apiRateLimitPerMinuteThousands | int | `780` | Rate limiting for Graph API requests per minute (in thousands) |
| connectorConfig.sharepoint.auth.clientId | string | `"{{ fail \"connectorConfig.sharepoint.auth.clientId is mandatory when auth.mode is certificate. Override in your deployment values.\" }}"` | Azure AD application client ID example: 00000000-0000-0000-0000-000000000000 The matching certificate (private key file) must be sourced and mounted from a secret |
| connectorConfig.sharepoint.auth.mode | string | `"certificate"` | authentication mode possible values: certificate |
| connectorConfig.sharepoint.auth.privateKeyPath | string | `"/app/key.pem"` | path to the private key file of the Azure AD application certificate in PEM format this closely relates to the volumeMounts and volume definitions users wanting to use another path can override this value and unset the volumeMounts and volume definitions if the key is encrypted, the password must be via a secret into a SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD environment variable |
| connectorConfig.sharepoint.auth.thumbprintSha1 | string | `""` | SHA1 thumbprint of the Azure AD application certificate users of the sharepoint-connector-secrets terraform module can get this from the modules outputs (thumbprint_sha1) users that provision their application registration manually can get this from the Azure portal |
| connectorConfig.sharepoint.baseUrl | string | `"{{ fail \"connectorConfig.sharepoint.baseUrl is mandatory. Override in your deployment values.\" }}"` | base url of the sharepoint instance example: https://acme.sharepoint.com |
| connectorConfig.sharepoint.siteDefaults | object | `{}` | Deployment-level defaults applied to every site (config_file rows or sharepoint_list rows). Per-site values always win when set; empty/blank values fall through to these defaults. Any field except siteId may be defaulted here. Leave as `{}` to keep today's behaviour where every field is supplied per-site. Example: siteDefaults:   syncColumnName: FinanceGPTKnowledge   ingestionMode: recursive   scopeId: scope_default   maxFilesToIngest: 1000   storeInternally: enabled   syncStatus: active   syncMode: content_only   permissionsInheritanceMode: inherit_scopes_and_files   subsitesScan: disabled |
| connectorConfig.sharepoint.sitesSource | string | `"config_file"` | Sites source configuration Determines how sites are configured: from static YAML (config_file) or dynamically from SharePoint list (sharepoint_list) possible values: config_file, sharepoint_list |
| connectorConfig.sharepoint.tenantId | string | `"{{ fail \"connectorConfig.sharepoint.tenantId is mandatory. Override in your deployment values.\" }}"` | tenant id against which the graph api calls are made example: 12345678-1234-1234-1234-123456789012 |
| connectorConfig.unique.apiRateLimitPerMinute | int | `100` | Number of Unique API requests allowed per minute |
| connectorConfig.unique.authMode | string | `"cluster_local"` | communication mode for the Unique Services possible values: cluster_local, external cluster_local: communicates using in-cluster URLs and requires serviceExtraHeaders with x-company-id and x-user-id external: communicates using external URLs and requires authentication via Zitadel |
| connectorConfig.unique.ingestionServiceBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}"` | base URL for the ingestion service; auto-derived from internalServices.dependencies.ingestion override with an explicit URL when authMode is external, e.g. https://api.unique.app/ingestion |
| connectorConfig.unique.scopeManagementServiceBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}"` | base URL for the scope management service; auto-derived from internalServices.dependencies.scopeManagement override with an explicit URL when authMode is external, e.g. https://api.unique.app/scope-management |
| connectorConfig.unique.serviceExtraHeaders | object | `{"x-company-id":"{{ fail \"connectorConfig.unique.serviceExtraHeaders.x-company-id is mandatory when authMode is cluster_local. Override in your deployment values.\" }}","x-user-id":"{{ fail \"connectorConfig.unique.serviceExtraHeaders.x-user-id is mandatory when authMode is cluster_local. Override in your deployment values.\" }}"}` | Object containing extra HTTP headers for Unique API requests (GraphQL and REST) Required when authMode is cluster_local. Must contain x-company-id and x-user-id headers. example: {"x-company-id": "1234567890", "x-user-id": "1234567890"} |
| connectorConfig.unique.zitadel | object | `{"clientId":"{{ fail \"connectorConfig.unique.zitadel.clientId is mandatory when authMode is external. Override in your deployment values.\" }}","oauthTokenUrl":"{{ fail \"connectorConfig.unique.zitadel.oauthTokenUrl is mandatory when authMode is external. Override in your deployment values.\" }}","projectId":"{{ fail \"connectorConfig.unique.zitadel.projectId is mandatory when authMode is external. Override in your deployment values.\" }}"}` | Zitadel authentication configuration (required when authMode is external) |
| connectorConfig.unique.zitadel.clientId | string | `"{{ fail \"connectorConfig.unique.zitadel.clientId is mandatory when authMode is external. Override in your deployment values.\" }}"` | Zitadel client ID |
| connectorConfig.unique.zitadel.oauthTokenUrl | string | `"{{ fail \"connectorConfig.unique.zitadel.oauthTokenUrl is mandatory when authMode is external. Override in your deployment values.\" }}"` | Zitadel OAuth token URL example: https://idp.unique.app/oauth/v2/token |
| connectorConfig.unique.zitadel.projectId | string | `"{{ fail \"connectorConfig.unique.zitadel.projectId is mandatory when authMode is external. Override in your deployment values.\" }}"` | Zitadel project ID example: 225317577440629999 |
| deployment.metadata.annotations."reloader.stakater.com/auto" | string | `"true"` |  |
| deployment.revisionHistoryLimit | int | `3` |  |
| env.LOGS_DIAGNOSTICS_CONFIG_EMIT_POLICY | string | `"{\"emit\":\"on\",\"events\":[\"on_startup\",\"on_sync\"]}"` |  |
| env.LOGS_DIAGNOSTICS_DATA_POLICY | string | `"conceal"` |  |
| env.LOG_LEVEL | string | `"info"` |  |
| env.MAX_FILE_SIZE_BYTES | string | `"209715200"` |  |
| env.MAX_HEAP_MB | int | `1920` |  |
| env.NODE_ENV | string | `"production"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"51346"` |  |
| env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| env.TENANT_CONFIG_PATH_PATTERN | string | `"/app/tenant-configs/*-tenant-config.yaml"` |  |
| envVars | list | `[]` | Environment variables from secrets. Example for loading secrets (uncomment and customize as needed):   envVars:     # For Zitadel authentication (required when authMode is 'external')     - name: ZITADEL_CLIENT_SECRET       valueFrom:         secretKeyRef:           name: sharepoint-connector-secret           key: ZITADEL_CLIENT_SECRET     # For encrypted certificate private key (optional, only if key is password-protected)     - name: SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD       valueFrom:         secretKeyRef:           name: sharepoint-connector-secret           key: SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD     # For proxy basic auth password (required when proxy.authMode is 'username_password')     - name: PROXY_PASSWORD       valueFrom:         secretKeyRef:           name: sharepoint-connector-secret           key: PROXY_PASSWORD |
| extraEnvCM | list | `["sharepoint-connector-proxy-config"]` | List of ConfigMaps to load as environment variables. The default assumes releaseName=sharepoint-connector. For multi-instance deployments with a different release name, override to match the rendered ConfigMap name (<releaseName>-proxy-config). |
| fullnameOverride | string | `"sharepoint-connector"` |  |
| grafana.dashboard.enabled | bool | `false` | Enable Grafana dashboard ConfigMap creation |
| grafana.dashboard.folder | string | `"connectors"` | Grafana folder where the dashboard will be placed |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.registry | string | `"ghcr.io"` |  |
| image.repository | string | `"unique-ag/connectors/services/sharepoint-connector"` |  |
| image.tag | string | `"2.7.0"` |  |
| internalServices.dependencies.ingestion.name | string | `"ingestion"` |  |
| internalServices.dependencies.ingestion.podPort | int | `8080` |  |
| internalServices.dependencies.ingestion.servicePort | int | `8091` |  |
| internalServices.dependencies.scopeManagement.name | string | `"scope-management"` |  |
| internalServices.dependencies.scopeManagement.podPort | int | `8080` |  |
| internalServices.dependencies.scopeManagement.servicePort | int | `8094` |  |
| nameOverride | string | `"sharepoint-connector"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[0].matchName | string | `"login.microsoftonline.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[1].matchPattern | string | `"*.sharepoint.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[2].matchName | string | `"graph.microsoft.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[3].matchPattern | string | `"*.microsoft.com"` |  |
| networkPolicy.baseline.egress.microsoft.toPorts[0].ports[0].port | string | `"443"` |  |
| networkPolicy.baseline.egress.microsoft.toPorts[0].ports[0].protocol | string | `"TCP"` |  |
| networkPolicy.baseline.prometheus.namespace | string | `"system"` |  |
| networkPolicy.enableDefaultDeny.egress | bool | `true` |  |
| networkPolicy.enableDefaultDeny.ingress | bool | `true` |  |
| networkPolicy.enabled | bool | `false` |  |
| networkPolicy.flavor | string | `"cilium"` |  |
| podLabels."logging.unique.app/format" | string | `"pino-json"` |  |
| ports.application | int | `51345` |  |
| ports.metrics | int | `51346` |  |
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
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.alert | string | `"SharepointConnectorGraphQLErrors"` |  |
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.annotations.description | string | `"The SharePoint Connector is experiencing GraphQL API errors (4xx/5xx responses). Current error rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes\n3. Verify network connectivity between connector and GraphQL API\n4. Verify authentication credentials and token validity\n5. Check for rate limiting or throttling issues\n"` |  |
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.annotations.summary | string | `"SharePoint Connector GraphQL API errors detected"` |  |
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.expr | string | `"(\n  sum(rate(spc_unique_graphql_api_request_duration_seconds_count{http_status_class=~\"4xx|5xx\"}[5m]))\n  /\n  sum(rate(spc_unique_graphql_api_request_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.for | string | `"30s"` |  |
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.labels.alertGroup | string | `"sharepoint-connector"` |  |
| prometheus.additionalAlerts.SharepointConnectorGraphQLErrors.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.alert | string | `"SharepointConnectorSyncFailures"` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.annotations.description | string | `"The SharePoint Connector is experiencing sync failures. Current failure rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check the failure_step label to identify where the sync failed\n3. Verify SharePoint connectivity and permissions\n4. Check for rate limiting or throttling issues\n5. Check for recent changes to the deployment as well as its underlying infrastructure\n"` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.annotations.summary | string | `"SharePoint Connector sync failures detected"` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.expr | string | `"(\n  sum(rate(spc_sync_duration_seconds_count{result=\"failure\"}[5m]))\n  /\n  sum(rate(spc_sync_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.for | string | `"30s"` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.labels.alertGroup | string | `"sharepoint-connector"` |  |
| prometheus.additionalAlerts.SharepointConnectorSyncFailures.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.alert | string | `"SharepointConnectorUniqueAPIErrors"` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.annotations.description | string | `"The SharePoint Connector is experiencing Unique REST API errors (4xx/5xx responses). Current error rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes (both the connector and the Unique Services)\n3. Verify network connectivity between connector and Unique Services\n4. Verify service user settings and permissions within Unique\n"` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.annotations.summary | string | `"SharePoint Connector Unique REST API errors detected"` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.expr | string | `"(\n  sum(rate(spc_unique_rest_api_request_duration_seconds_count{http_status_class=~\"4xx|5xx\"}[5m]))\n  /\n  sum(rate(spc_unique_rest_api_request_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.for | string | `"30s"` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.labels.alertGroup | string | `"sharepoint-connector"` |  |
| prometheus.additionalAlerts.SharepointConnectorUniqueAPIErrors.labels.severity | string | `"warning"` |  |
| proxyConfig | object | `{"authMode":"none","enabled":true}` | HTTP proxy configuration for external API calls Required for environments where internet access is only available through a proxy. Users preferring setting all variables by hand disable the enabled flag and remove the proxy-config ConfigMap from extraEnvCM. |
| proxyConfig.authMode | string | `"none"` | Proxy authentication mode none: proxy disabled no_auth: proxy enabled, no authentication username_password: username/password authentication ssl_tls: TLS client certificate authentication |
| proxyConfig.enabled | bool | `true` | if disabled, the proxy-config ConfigMap must be removed from extraEnvCM. |
| resources.limits.memory | string | `"2048Mi"` |  |
| resources.requests.cpu | int | `1` |  |
| resources.requests.memory | string | `"1984Mi"` |  |
| routes.hostname | string | `""` |  |
| selectorComponentLabel | string | `"server"` |  |
| service.enabled | bool | `false` |  |
| serviceAccount.enabled | bool | `true` |  |
| volumeMounts[0].mountPath | string | `"/tmp"` |  |
| volumeMounts[0].name | string | `"tmp"` |  |
| volumeMounts[1].mountPath | string | `"/app/key.pem"` |  |
| volumeMounts[1].name | string | `"sharepoint-connector-secret"` |  |
| volumeMounts[1].readOnly | bool | `true` |  |
| volumeMounts[1].subPath | string | `"key.pem"` |  |
| volumeMounts[2] | object | `{"mountPath":"/app/tenant-configs","name":"tenant-config","readOnly":true}` | Mount tenant configuration directory |
| volumes[0].emptyDir | object | `{}` |  |
| volumes[0].name | string | `"tmp"` |  |
| volumes[1] | object | `{"name":"sharepoint-connector-secret","secret":{"items":[{"key":"key.pem","path":"key.pem"}],"secretName":"sharepoint-connector-secret"}}` | Graph/SharePoint Certificate Secret by default the chart expects the certificate to be in a secret named sharepoint-connector-secret under the key key.pem Users can supersede this with their own secret that contains the certificate under a different key or use their own secret name Users must also set the connectorConfig.sharepoint.auth.privateKeyPath to the path of the certificate in the secret |
| volumes[2] | object | `{"configMap":{"name":"sharepoint-connector-tenant-config"},"name":"tenant-config"}` | Tenant configuration YAML file mounted from ConfigMap. The default assumes releaseName=sharepoint-connector. For multi-instance deployments with a different release name, override to match the rendered ConfigMap name (<releaseName>-tenant-config). |
| workloadIdentity.azure.clientId | string | `"unset_default_value"` |  |
| workloadIdentity.azure.enabled | bool | `true` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
