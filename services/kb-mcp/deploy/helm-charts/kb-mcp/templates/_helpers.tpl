{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
mcpConfig environment variables — non-secret fields with tenant-specific values.
Secrets, the Zitadel client ID, and ZITADEL_JWT_SIGNING_KEY (never sent to
Zitadel) stay in envVars/secret refs.
*/}}
{{- define "chart.config.mcpEnv" -}}
{{- if .Values.mcpConfig.app.publicBaseUrl }}
- name: UNIQUE_MCP_PUBLIC_BASE_URL
  value: {{ tpl .Values.mcpConfig.app.publicBaseUrl . | quote }}
{{- end }}
{{- if .Values.mcpConfig.app.frontendBaseUrl }}
- name: UNIQUE_MCP_FRONTEND_BASE_URL
  value: {{ tpl .Values.mcpConfig.app.frontendBaseUrl . | quote }}
{{- end }}
{{- if .Values.mcpConfig.zitadel.baseUrl }}
- name: ZITADEL_BASE_URL
  value: {{ tpl .Values.mcpConfig.zitadel.baseUrl . | quote }}
{{- end }}
{{- if .Values.mcpConfig.enabledTools }}
- name: KB_MCP_ENABLED_TOOLS
  value: {{ join "," .Values.mcpConfig.enabledTools | quote }}
{{- end }}
{{- if .Values.mcpConfig.search.scopeLookupConcurrency }}
- name: KB_MCP_SEARCH_SCOPE_LOOKUP_CONCURRENCY
  value: {{ .Values.mcpConfig.search.scopeLookupConcurrency | quote }}
{{- end }}
{{- $walk := .Values.mcpConfig.folderWalk | default dict }}
{{- $cache := $walk.cache | default dict }}
{{- if $cache.ttlSeconds }}
- name: KB_MCP_TREE_CACHE_TTL_SECONDS
  value: {{ $cache.ttlSeconds | quote }}
{{- end }}
{{- if $cache.maxEntries }}
- name: KB_MCP_TREE_CACHE_MAX_ENTRIES
  value: {{ $cache.maxEntries | quote }}
{{- end }}
{{/* hasKey preserves explicit zero values, which Helm treats as false. */}}
{{- if hasKey $walk "timeoutSeconds" }}
- name: KB_MCP_WALK_TIMEOUT_SECONDS
  value: {{ $walk.timeoutSeconds | quote }}
{{- end }}
{{- if hasKey $walk "maxTimeoutSeconds" }}
- name: KB_MCP_WALK_MAX_TIMEOUT_SECONDS
  value: {{ $walk.maxTimeoutSeconds | quote }}
{{- end }}
{{- if .Values.mcpConfig.http.maxConnections }}
- name: KB_MCP_HTTP_MAX_CONNECTIONS
  value: {{ .Values.mcpConfig.http.maxConnections | quote }}
{{- end }}
{{- if .Values.mcpConfig.http.maxKeepaliveConnections }}
- name: KB_MCP_HTTP_MAX_KEEPALIVE_CONNECTIONS
  value: {{ .Values.mcpConfig.http.maxKeepaliveConnections | quote }}
{{- end }}
{{- if .Values.mcpConfig.http.poolTimeoutSeconds }}
- name: KB_MCP_HTTP_POOL_TIMEOUT_SECONDS
  value: {{ .Values.mcpConfig.http.poolTimeoutSeconds | quote }}
{{- end }}
{{- end -}}
