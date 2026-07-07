{{- define "base.deployment.container.app.env.ext" -}}
{{- if .Values.mcpConfig.enabled }}
- name: SELF_URL
  value: {{ tpl .Values.mcpConfig.app.selfUrl . | quote }}
- name: MICROSOFT_CLIENT_ID
  value: {{ tpl .Values.mcpConfig.microsoft.clientId . | quote }}
{{- if .Values.mcpConfig.microsoft.publicWebhookUrl }}
- name: MICROSOFT_PUBLIC_WEBHOOK_URL
  value: {{ .Values.mcpConfig.microsoft.publicWebhookUrl | quote }}
{{- end }}
{{- if .Values.mcpConfig.microsoft.autoStartIngestion }}
- name: MICROSOFT_AUTO_START_INGESTION
  value: {{ .Values.mcpConfig.microsoft.autoStartIngestion | quote }}
{{- end }}
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
- name: AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS
  value: {{ .Values.mcpConfig.auth.accessTokenExpiresInSeconds | quote }}
- name: AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS
  value: {{ .Values.mcpConfig.auth.refreshTokenExpiresInSeconds | quote }}
{{- end }}
{{- end -}}
