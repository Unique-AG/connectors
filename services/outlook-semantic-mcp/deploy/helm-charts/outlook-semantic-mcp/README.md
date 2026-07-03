# outlook-semantic-mcp

![Version: 2.0.2](https://img.shields.io/badge/Version-2.0.2-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 2.0.2](https://img.shields.io/badge/AppVersion-2.0.2-informational?style=flat-square)

An experimental MCP server for Outlook leveraging the Microsoft Graph API.

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/unique-ag/helm | base | 0.1.0-4c70c3 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| deployment.metadata.annotations."reloader.stakater.com/auto" | string | `"true"` |  |
| deployment.revisionHistoryLimit | int | `3` |  |
| env.LOG_LEVEL | string | `"info"` |  |
| env.MAX_HEAP_MB | int | `850` |  |
| env.NODE_ENV | string | `"production"` |  |
| env.OTEL_EXPORTER_OTLP_ENDPOINT.if | string | `"{{ .Values.internalServices.dependencies.otelTraces.enabled }}"` |  |
| env.OTEL_EXPORTER_OTLP_ENDPOINT.value | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.otelTraces) }}"` |  |
| env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT.if | string | `"{{ .Values.internalServices.dependencies.otelTraces.enabled }}"` |  |
| env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT.value | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.otelTraces) }}/v1/traces"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"51346"` |  |
| env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| envVars | list | `[]` | Environment variables from secrets. Example for loading secrets (uncomment and customize as needed):   envVars:     # For Zitadel authentication (required when authMode is 'external')     - name: UNIQUE_ZITADEL_CLIENT_SECRET       valueFrom:         secretKeyRef:           name: outlook-semantic-mcp-zitadel-secret           key: UNIQUE_ZITADEL_CLIENT_SECRET |
| extraEnvCM | list | `["outlook-semantic-mcp-config"]` | ConfigMap(s) to load environment variables from. Default assumes release name is "outlook-semantic-mcp" (i.e., base.fullname resolves to "outlook-semantic-mcp"). Override with [<your-fullname>-config] if using a different release name or fullnameOverride. |
| fullnameOverride | string | `"outlook-semantic-mcp"` |  |
| grafana.dashboard.enabled | bool | `true` | Enable Grafana dashboard ConfigMap creation |
| grafana.dashboard.folder | string | `"mcp-servers"` | Grafana folder where the dashboard will be placed |
| hooks.migration.command | string | `"pnpm run db:migrate\n"` |  |
| hooks.migration.enabled | bool | `true` |  |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.registry | string | `"ghcr.io"` |  |
| image.repository | string | `"unique-ag/connectors/services/outlook-semantic-mcp"` |  |
| image.tag | string | `"2.0.2"` |  |
| ingress.additionalLabels | object | `{}` | Additional labels for the ingress resource |
| ingress.annotations | object | `{"konghq.com/plugins":"unique-route-metrics"}` | Annotations for the ingress resource |
| ingress.enabled | bool | `false` | Enable ingress resource creation |
| ingress.hosts | list | `[]` | Ingress hosts configuration |
| ingress.ingressClassName | string | `"kong"` | Ingress class name (e.g., nginx, traefik) |
| ingress.tls | list | `[]` | TLS configuration for the ingress |
| internalServices.dependencies.ingestion.name | string | `"ingestion"` |  |
| internalServices.dependencies.ingestion.podPort | int | `8080` |  |
| internalServices.dependencies.ingestion.servicePort | int | `8091` |  |
| internalServices.dependencies.otelTraces.enabled | bool | `false` |  |
| internalServices.dependencies.otelTraces.name | string | `"otel-traces"` |  |
| internalServices.dependencies.otelTraces.servicePort | int | `4318` |  |
| internalServices.dependencies.scopeManagement.name | string | `"scope-management"` |  |
| internalServices.dependencies.scopeManagement.podPort | int | `8080` |  |
| internalServices.dependencies.scopeManagement.servicePort | int | `8094` |  |
| internalServices.dependents.ingressGateway.name | string | `"gateway"` |  |
| internalServices.dependents.ingressGateway.namespace | string | `"system"` |  |
| mcpConfig | object | `{"app":{"mcpBackend":"microsoft_graph_and_unique_api","mcpDebugMode":"disabled","selfUrl":"{{ fail \"mcpConfig.app.selfUrl is mandatory. Override in your deployment values.\" }}"},"delegatedAccess":{"scan":"disabled"},"enabled":true,"ingestion":{"defaultMailFilters":{"ignoredContents":[],"ignoredSenders":[],"retentionWindowInDays":95}},"microsoft":{"clientId":"{{ fail \"mcpConfig.microsoft.clientId is mandatory. Override in your deployment values.\" }}"},"unique":{"ingestionServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}","scopeManagementServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}","serviceAuthMode":"cluster_local","serviceExtraHeaders":{},"zitadel":{"clientId":"{{ fail \"mcpConfig.unique.zitadel.clientId is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}","oauthTokenUrl":"{{ fail \"mcpConfig.unique.zitadel.oauthTokenUrl is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}","projectId":"{{ fail \"mcpConfig.unique.zitadel.projectId is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}"}}}` | Configuration for the deployed Outlook Semantic MCP Server, will be mapped to environment variables Users preferring setting all variables by hand disable the enabled flag and set the extraEnvCM to [] |
| mcpConfig.app | object | `{"mcpBackend":"microsoft_graph_and_unique_api","mcpDebugMode":"disabled","selfUrl":"{{ fail \"mcpConfig.app.selfUrl is mandatory. Override in your deployment values.\" }}"}` | Application configuration |
| mcpConfig.app.mcpBackend | string | `"microsoft_graph_and_unique_api"` | Search backend. microsoft_graph_and_unique_api: dual backend, KB ingestion + semantic search (default). microsoft_graph: direct Graph search, no ingestion, sync tools not registered. |
| mcpConfig.app.mcpDebugMode | string | `"disabled"` | Debug mode for the MCP server. Set to "enabled" to expose:    1. Debugging tools    2. Extra debugging data in tool responses. |
| mcpConfig.app.selfUrl | string | `"{{ fail \"mcpConfig.app.selfUrl is mandatory. Override in your deployment values.\" }}"` | The URL of the MCP Server. Used for OAuth callbacks. The URL must be reachable from the redirect location, e.g. must be publicly accessible. example: https://outlook.mcp.unique.app |
| mcpConfig.delegatedAccess | object | `{"scan":"disabled"}` | Delegated access configuration. Controls whether the service discovers shared mailbox access. |
| mcpConfig.delegatedAccess.scan | string | `"disabled"` | Scanning mode. Values: disabled | full_access_only | granular_access   disabled         - delegated access scanning is off (default)   full_access_only - discovers Full Access (Read & Manage) delegation via /messages endpoint   granular_access  - discovers folder-level delegation via /mailFolders endpoint + runs verification Env var: DELEGATED_ACCESS_SCAN |
| mcpConfig.enabled | bool | `true` | if disabled, extraEnvCM must be set to [] |
| mcpConfig.ingestion | object | `{"defaultMailFilters":{"ignoredContents":[],"ignoredSenders":[],"retentionWindowInDays":95}}` | Ingestion backend configuration. Required when mcpBackend is 'microsoft_graph_and_unique_api'. Omit entirely for 'microsoft_graph'. |
| mcpConfig.ingestion.defaultMailFilters | object | `{"ignoredContents":[],"ignoredSenders":[],"retentionWindowInDays":95}` | Required. Default mail filters applied when creating a new inbox configuration. retentionWindowInDays: limits sync to emails received within the last N days (rolling). Env var: INGESTION_DEFAULT_MAIL_FILTERS (JSON string) |
| mcpConfig.microsoft | object | `{"clientId":"{{ fail \"mcpConfig.microsoft.clientId is mandatory. Override in your deployment values.\" }}"}` | Microsoft Graph API configuration |
| mcpConfig.microsoft.clientId | string | `"{{ fail \"mcpConfig.microsoft.clientId is mandatory. Override in your deployment values.\" }}"` | The client ID of the Microsoft App Registration example: 12345678-1234-1234-1234-123456789012 |
| mcpConfig.unique | object | `{"ingestionServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}","scopeManagementServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}","serviceAuthMode":"cluster_local","serviceExtraHeaders":{},"zitadel":{"clientId":"{{ fail \"mcpConfig.unique.zitadel.clientId is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}","oauthTokenUrl":"{{ fail \"mcpConfig.unique.zitadel.oauthTokenUrl is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}","projectId":"{{ fail \"mcpConfig.unique.zitadel.projectId is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}"}}` | Unique API configuration |
| mcpConfig.unique.ingestionServiceBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}"` | Base URL for Unique ingestion service; auto-derived from internalServices.dependencies.ingestion override with an explicit URL when serviceAuthMode is external, e.g. https://api.unique.app/ingestion |
| mcpConfig.unique.scopeManagementServiceBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.scopeManagement) }}"` | Base URL for Unique scope management; auto-derived from internalServices.dependencies.scopeManagement override with an explicit URL when serviceAuthMode is external, e.g. https://api.unique.app/scope-management |
| mcpConfig.unique.serviceAuthMode | string | `"cluster_local"` | Authentication mode for Unique API services possible values: cluster_local, external cluster_local: communicates using in-cluster URLs with service headers external: communicates using external URLs with app key authentication |
| mcpConfig.unique.serviceExtraHeaders | object | `{}` | Extra headers to send with requests to Unique API services (JSON string) For cluster_local mode: '{"x-company-id": "...", "x-user-id": "..."}' |
| mcpConfig.unique.zitadel | object | `{"clientId":"{{ fail \"mcpConfig.unique.zitadel.clientId is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}","oauthTokenUrl":"{{ fail \"mcpConfig.unique.zitadel.oauthTokenUrl is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}","projectId":"{{ fail \"mcpConfig.unique.zitadel.projectId is mandatory when serviceAuthMode is external. Override in your deployment values.\" }}"}` | Optional. Whether to store emails internally in the Unique knowledge base. To override: storeInternally: enabled Or set env var directly: UNIQUE_STORE_INTERNALLY=enabled Zitadel config |
| nameOverride | string | `"outlook-semantic-mcp"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[0].matchName | string | `"login.microsoftonline.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[1].matchName | string | `"graph.microsoft.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[2].matchPattern | string | `"*.microsoft.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[3].matchName | string | `"outlook.office.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[4].matchName | string | `"outlook.office365.com"` |  |
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
| postgresql.connection.sslMode | string | `"verify"` |  |
| postgresql.enabled | bool | `true` |  |
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
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.alert | string | `"OutlookSemanticMcpGraphQLErrors"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.annotations.description | string | `"The Outlook Semantic MCP server is experiencing GraphQL API errors (4xx/5xx responses). Current error rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes\n3. Verify network connectivity between MCP server and GraphQL API\n4. Verify authentication credentials and token validity\n5. Check for rate limiting or throttling issues\n"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.annotations.summary | string | `"Outlook Semantic MCP GraphQL API errors detected"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.expr | string | `"(\n  sum(rate(outlook_semantic_mcp_unique_graphql_api_request_duration_seconds_count{http_status_class=~\"4xx|5xx\"}[5m]))\n  /\n  sum(rate(outlook_semantic_mcp_unique_graphql_api_request_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.for | string | `"30s"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.labels.alertGroup | string | `"outlook-semantic-mcp"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpGraphQLErrors.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.alert | string | `"OutlookSemanticMcpUniqueAPIErrors"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.annotations.description | string | `"The Outlook Semantic MCP server is experiencing Unique REST API errors (4xx/5xx responses). Current error rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes (both the MCP server and the Unique Services)\n3. Verify network connectivity between MCP server and Unique Services\n4. Verify service user settings and permissions within Unique\n"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.annotations.summary | string | `"Outlook Semantic MCP Unique REST API errors detected"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.expr | string | `"(\n  sum(rate(outlook_semantic_mcp_unique_rest_api_request_duration_seconds_count{http_status_class=~\"4xx|5xx\"}[5m]))\n  /\n  sum(rate(outlook_semantic_mcp_unique_rest_api_request_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.for | string | `"30s"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.labels.alertGroup | string | `"outlook-semantic-mcp"` |  |
| prometheus.additionalAlerts.OutlookSemanticMcpUniqueAPIErrors.labels.severity | string | `"warning"` |  |
| rabbitmq.connection | object | `{}` |  |
| rabbitmq.enabled | bool | `true` |  |
| resources.limits.memory | string | `"1Gi"` |  |
| resources.requests.cpu | int | `1` |  |
| resources.requests.memory | string | `"512Mi"` |  |
| routes.hostname | string | `""` |  |
| selectorComponentLabel | string | `"server"` |  |
| service.port | int | `80` |  |
| serviceAccount.enabled | bool | `true` |  |
| volumeMounts[0].mountPath | string | `"/tmp"` |  |
| volumeMounts[0].name | string | `"tmp"` |  |
| volumes[0].emptyDir.sizeLimit | string | `"20Gi"` |  |
| volumes[0].name | string | `"tmp"` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
