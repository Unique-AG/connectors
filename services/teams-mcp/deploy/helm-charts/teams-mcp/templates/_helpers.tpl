{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
Ensure URL has trailing slash.
Accepts a context with .url containing the URL to process.
*/}}
{{- define "chart.ensureTrailingSlash" -}}
{{- $url := .url }}
{{- if hasSuffix "/" $url }}
{{- $url }}
{{- else }}
{{- printf "%s/" $url }}
{{- end }}
{{- end }}

{{/*
All mcpConfig environment variables, shared by deployment and hook job containers.
*/}}
{{- define "chart.config.mcpEnv" -}}
- name: SELF_URL
  value: {{ tpl .Values.mcpConfig.app.selfUrl . | quote }}
- name: MICROSOFT_CLIENT_ID
  value: {{ tpl .Values.mcpConfig.microsoft.clientId . | quote }}
{{- if .Values.mcpConfig.microsoft.publicWebhookUrl }}
- name: MICROSOFT_PUBLIC_WEBHOOK_URL
  value: {{ .Values.mcpConfig.microsoft.publicWebhookUrl | quote }}
{{- end }}
- name: UNIQUE_INTEGRATION
  value: {{ .Values.mcpConfig.unique.integration | quote }}
{{- if eq .Values.mcpConfig.unique.integration "enabled" }}
- name: UNIQUE_SERVICE_AUTH_MODE
  value: {{ .Values.mcpConfig.unique.serviceAuthMode | quote }}
- name: UNIQUE_API_BASE_URL
  value: {{ include "chart.ensureTrailingSlash" (dict "url" (tpl .Values.mcpConfig.unique.apiBaseUrl .)) | quote }}
- name: UNIQUE_API_VERSION
  value: {{ .Values.mcpConfig.unique.apiVersion | quote }}
- name: UNIQUE_ROOT_SCOPE_ID
  value: {{ .Values.mcpConfig.unique.rootScopeId | quote }}
- name: UNIQUE_USER_FETCH_CONCURRENCY
  value: {{ .Values.mcpConfig.unique.userFetchConcurrency | quote }}
- name: UNIQUE_SERVICE_EXTRA_HEADERS
  value: {{ .Values.mcpConfig.unique.serviceExtraHeaders | toJson | quote }}
{{- if eq .Values.mcpConfig.unique.serviceAuthMode "cluster_local" }}
- name: UNIQUE_INGESTION_SERVICE_BASE_URL
  value: {{ include "chart.ensureTrailingSlash" (dict "url" (tpl .Values.mcpConfig.unique.ingestionServiceBaseUrl .)) | quote }}
{{- end }}
{{- if .Values.mcpConfig.unique.autoStartIngestion }}
- name: UNIQUE_AUTO_START_INGESTION
  value: {{ .Values.mcpConfig.unique.autoStartIngestion | quote }}
{{- end }}
{{- end }}
- name: AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS
  value: {{ .Values.mcpConfig.auth.accessTokenExpiresInSeconds | quote }}
- name: AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS
  value: {{ .Values.mcpConfig.auth.refreshTokenExpiresInSeconds | quote }}
{{- end -}}
