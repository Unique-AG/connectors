{{/* mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00 */}}
{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
mcpConfig as container env vars. A field renders only when set: a string when not empty, any
other value when not null, so 0 and false still render.
*/}}
{{- define "chart.config.mcpEnv" -}}
{{- $config := .Values.mcpConfig }}
{{- $zitadel := dict }}
{{- if eq $config.auth.mode "zitadel" }}
{{- $zitadel = $config.auth.zitadel }}
{{- end }}
{{- $strings := list
  (list $config.server.baseUrl "MCP_BASE_URL")
  (list $config.auth.mode "MCP_AUTH_MODE")
  (list $zitadel.baseUrl "ZITADEL_BASE_URL")
  (list $zitadel.clientId "ZITADEL_CLIENT_ID")
  (list $zitadel.orgId "ZITADEL_ORG_ID")
  (list $config.polixis.apiUrl "UPSTREAM_API_URL")
  (list $config.polixis.tokenUrl "UPSTREAM_TOKEN_URL")
  (list $config.logging.level "LOG_LEVEL")
  (list $config.logging.diagnosticsDataPolicy "LOGS_DIAGNOSTICS_DATA_POLICY")
  (list $config.logging.errorDetailsPolicy "ERROR_DETAILS_POLICY")
}}
{{- range $pair := $strings }}
{{- if first $pair }}
- name: {{ last $pair }}
  value: {{ tpl (first $pair) $ | quote }}
{{- end }}
{{- end }}
{{- $values := list
  (list $config.polixis.timeoutSeconds "UPSTREAM_TIMEOUT_SECONDS")
  (list $config.polixis.maxConcurrentRequests "UPSTREAM_MAX_CONCURRENT_REQUESTS")
  (list $config.polixis.quotaCooldownSeconds "UPSTREAM_QUOTA_COOLDOWN_SECONDS")
  (list $config.polixis.retry.enabled "UPSTREAM_RETRY_ENABLED")
  (list $config.polixis.retry.maxAttempts "UPSTREAM_RETRY_MAX_ATTEMPTS")
  (list $config.polixis.retry.maxWaitSeconds "UPSTREAM_RETRY_MAX_WAIT_SECONDS")
  (list $config.rateLimit.toolCallsPerWindow "MCP_RATE_LIMIT_TOOL_CALLS_PER_WINDOW")
  (list $config.rateLimit.windowSeconds "MCP_RATE_LIMIT_WINDOW_SECONDS")
}}
{{- range $pair := $values }}
{{- if not (kindIs "invalid" (first $pair)) }}
- name: {{ last $pair }}
  value: {{ first $pair | toString | quote }}
{{- end }}
{{- end }}
{{- if $config.logging.libraryLevels }}
- name: LIBRARY_LOG_LEVELS
  value: {{ toJson $config.logging.libraryLevels | quote }}
{{- end }}
{{- end -}}
