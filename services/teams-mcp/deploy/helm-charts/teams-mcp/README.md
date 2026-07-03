# teams-mcp

![Version: 0.2.22](https://img.shields.io/badge/Version-0.2.22-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 0.2.22](https://img.shields.io/badge/AppVersion-0.2.22-informational?style=flat-square)

An experimental MCP server for Teams leveraging the Microsoft Graph API.

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
| env.MAX_HEAP_MB | int | `1920` |  |
| env.NODE_ENV | string | `"production"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_HOST | string | `"0.0.0.0"` |  |
| env.OTEL_EXPORTER_PROMETHEUS_PORT | string | `"51346"` |  |
| env.OTEL_METRICS_EXPORTER | string | `"prometheus"` |  |
| envVars | list | `[]` | Environment variables from secrets (required secrets listed at bottom of file) |
| extraEnvCM | list | `["teams-mcp-config"]` | ConfigMap(s) to load environment variables from (must match release name + '-config') |
| fullnameOverride | string | `"teams-mcp"` |  |
| grafana.dashboard.enabled | bool | `true` | Enable Grafana dashboard ConfigMap creation |
| grafana.dashboard.folder | string | `"mcp-servers"` | Grafana folder where the dashboard will be placed |
| hooks.migration.command | string | `"pnpm run db:migrate\n"` |  |
| hooks.migration.enabled | bool | `true` |  |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.registry | string | `"ghcr.io"` |  |
| image.repository | string | `"unique-ag/connectors/services/teams-mcp"` |  |
| image.tag | string | `"0.2.22"` |  |
| ingress.additionalLabels | object | `{}` | Additional labels for the ingress resource |
| ingress.annotations | object | `{"konghq.com/plugins":"unique-route-metrics"}` | Annotations for the ingress resource |
| ingress.enabled | bool | `false` | Enable ingress resource creation |
| ingress.hosts | list | `[]` | Ingress hosts configuration |
| ingress.ingressClassName | string | `"kong"` | Ingress class name (e.g., nginx, traefik) |
| ingress.tls | list | `[]` | TLS configuration for the ingress |
| internalServices.dependencies.chat.name | string | `"chat"` |  |
| internalServices.dependencies.chat.podPort | int | `8080` |  |
| internalServices.dependencies.chat.servicePort | int | `8093` |  |
| internalServices.dependencies.ingestion.name | string | `"ingestion"` |  |
| internalServices.dependencies.ingestion.podPort | int | `8080` |  |
| internalServices.dependencies.ingestion.servicePort | int | `8091` |  |
| internalServices.dependents.ingressGateway.name | string | `"gateway"` |  |
| internalServices.dependents.ingressGateway.namespace | string | `"system"` |  |
| mcpConfig | object | `{"app":{"selfUrl":"{{ fail \"mcpConfig.app.selfUrl is mandatory. Override in your deployment values.\" }}"},"auth":{"accessTokenExpiresInSeconds":60,"refreshTokenExpiresInSeconds":2592000},"enabled":true,"microsoft":{"autoStartIngestion":false,"clientId":"{{ fail \"mcpConfig.microsoft.clientId is mandatory. Override in your deployment values.\" }}"},"unique":{"apiBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.chat) }}/public/","apiVersion":"2023-12-06","ingestionServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}","rootScopeId":"","serviceAuthMode":"cluster_local","serviceExtraHeaders":{},"userFetchConcurrency":5}}` | Configuration for the deployed Teams MCP Server, will be mapped to environment variables Users preferring setting all variables by hand disable the enabled flag and set the extraEnvCM to [] |
| mcpConfig.app | object | `{"selfUrl":"{{ fail \"mcpConfig.app.selfUrl is mandatory. Override in your deployment values.\" }}"}` | Application configuration |
| mcpConfig.app.selfUrl | string | `"{{ fail \"mcpConfig.app.selfUrl is mandatory. Override in your deployment values.\" }}"` | The URL of the MCP Server. Used for OAuth callbacks. The URL must be reachable from the redirect location, e.g. must be publicly accessible. example: https://teams.mcp.unique.app |
| mcpConfig.auth | object | `{"accessTokenExpiresInSeconds":60,"refreshTokenExpiresInSeconds":2592000}` | Authentication configuration for the MCP server |
| mcpConfig.auth.accessTokenExpiresInSeconds | int | `60` | Access token expiration time in seconds |
| mcpConfig.auth.refreshTokenExpiresInSeconds | int | `2592000` | Refresh token expiration time in seconds (default: 30 days) |
| mcpConfig.enabled | bool | `true` | if disabled, extraEnvCM must be set to [] |
| mcpConfig.microsoft | object | `{"autoStartIngestion":false,"clientId":"{{ fail \"mcpConfig.microsoft.clientId is mandatory. Override in your deployment values.\" }}"}` | Microsoft Graph API configuration |
| mcpConfig.microsoft.autoStartIngestion | bool | `false` | When enabled, automatically enqueue a transcript subscription for every user at login (skips the start_kb_integration tool). |
| mcpConfig.microsoft.clientId | string | `"{{ fail \"mcpConfig.microsoft.clientId is mandatory. Override in your deployment values.\" }}"` | The client ID of the Microsoft App Registration example: 12345678-1234-1234-1234-123456789012 |
| mcpConfig.unique | object | `{"apiBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.chat) }}/public/","apiVersion":"2023-12-06","ingestionServiceBaseUrl":"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}","rootScopeId":"","serviceAuthMode":"cluster_local","serviceExtraHeaders":{},"userFetchConcurrency":5}` | Unique API configuration |
| mcpConfig.unique.apiBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.chat) }}/public/"` | The Public API URL; auto-derived from internalServices.dependencies.chat with /public/ suffix override with an explicit URL when serviceAuthMode is external, e.g. https://gateway.unique.app/public/chat/ |
| mcpConfig.unique.apiVersion | string | `"2023-12-06"` | The Public API version to use |
| mcpConfig.unique.ingestionServiceBaseUrl | string | `"{{ include \"base.internalService.url\" (dict \"root\" . \"dep\" .Values.internalServices.dependencies.ingestion) }}"` | Base URL for Unique ingestion service; auto-derived from internalServices.dependencies.ingestion override with an explicit URL when serviceAuthMode is external, e.g. https://api.unique.app/ingestion |
| mcpConfig.unique.rootScopeId | string | (required) | The root scope ID under which to create transcript and recording folders |
| mcpConfig.unique.serviceAuthMode | string | `"cluster_local"` | Authentication mode for Unique API services possible values: cluster_local, external cluster_local: communicates using in-cluster URLs with service headers external: communicates using external URLs with app key authentication |
| mcpConfig.unique.serviceExtraHeaders | object | `{}` | Extra headers to send with requests to Unique API services (JSON string) For cluster_local mode: '{"x-company-id": "...", "x-user-id": "..."}' |
| mcpConfig.unique.userFetchConcurrency | int | `5` | Concurrency limit for fetching users when resolving scope accesses |
| nameOverride | string | `"teams-mcp"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[0].matchName | string | `"login.microsoftonline.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[1].matchName | string | `"graph.microsoft.com"` |  |
| networkPolicy.baseline.egress.microsoft.toFQDNs[2].matchPattern | string | `"*.microsoft.com"` |  |
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
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.alert | string | `"TeamsMcpGraphQLErrors"` |  |
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.annotations.description | string | `"The Teams MCP server is experiencing GraphQL API errors (4xx/5xx responses). Current error rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes\n3. Verify network connectivity between MCP server and GraphQL API\n4. Verify authentication credentials and token validity\n5. Check for rate limiting or throttling issues\n"` |  |
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.annotations.summary | string | `"Teams MCP GraphQL API errors detected"` |  |
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.expr | string | `"(\n  sum(rate(teams_mcp_unique_graphql_api_request_duration_seconds_count{http_status_class=~\"4xx|5xx\"}[5m]))\n  /\n  sum(rate(teams_mcp_unique_graphql_api_request_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.for | string | `"30s"` |  |
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.labels.alertGroup | string | `"teams-mcp"` |  |
| prometheus.additionalAlerts.TeamsMcpGraphQLErrors.labels.severity | string | `"warning"` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.alert | string | `"TeamsMcpUniqueAPIErrors"` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.annotations.description | string | `"The Teams MCP server is experiencing Unique REST API errors (4xx/5xx responses). Current error rate: {{ $value | humanizePercentage }}."` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.annotations.runbook | string | `"1. Inspect application logs for specific error messages\n2. Check for recent deployments or configuration changes (both the MCP server and the Unique Services)\n3. Verify network connectivity between MCP server and Unique Services\n4. Verify service user settings and permissions within Unique\n"` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.annotations.summary | string | `"Teams MCP Unique REST API errors detected"` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.expr | string | `"(\n  sum(rate(teams_mcp_unique_rest_api_request_duration_seconds_count{http_status_class=~\"4xx|5xx\"}[5m]))\n  /\n  sum(rate(teams_mcp_unique_rest_api_request_duration_seconds_count[5m]))\n) > 0.01\n"` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.for | string | `"30s"` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.labels.alertGroup | string | `"teams-mcp"` |  |
| prometheus.additionalAlerts.TeamsMcpUniqueAPIErrors.labels.severity | string | `"warning"` |  |
| rabbitmq.connection | object | `{}` |  |
| rabbitmq.enabled | bool | `true` |  |
| resources.limits.ephemeral-storage | string | `"10Gi"` |  |
| resources.limits.memory | string | `"2048Mi"` |  |
| resources.requests.cpu | int | `1` |  |
| resources.requests.ephemeral-storage | string | `"6Gi"` |  |
| resources.requests.memory | string | `"1984Mi"` |  |
| routes.hostname | string | `""` |  |
| selectorComponentLabel | string | `"server"` |  |
| service.port | int | `80` |  |
| serviceAccount.enabled | bool | `true` |  |
| volumeMounts[0].mountPath | string | `"/tmp"` |  |
| volumeMounts[0].name | string | `"tmp"` |  |
| volumes[0].emptyDir.sizeLimit | string | `"10Gi"` |  |
| volumes[0].name | string | `"tmp"` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
