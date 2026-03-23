{{- define "chart.config.unique" -}}
UNIQUE_SERVICE_AUTH_MODE: {{ .Values.mcpConfig.unique.serviceAuthMode | quote }}
UNIQUE_INGESTION_SERVICE_BASE_URL: {{ include "chart.ensureNoTrailingSlash" (dict "url" .Values.mcpConfig.unique.ingestionServiceBaseUrl) | quote }}
UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL: {{ include "chart.ensureNoTrailingSlash" (dict "url" .Values.mcpConfig.unique.scopeManagementServiceBaseUrl) | quote }}
{{- if .Values.mcpConfig.unique.storeInternally }}
UNIQUE_STORE_INTERNALLY: {{ .Values.mcpConfig.unique.storeInternally | quote }}
{{- end }}
{{- if eq .Values.mcpConfig.unique.serviceAuthMode "cluster_local" }}
UNIQUE_SERVICE_EXTRA_HEADERS: '{{ .Values.mcpConfig.unique.serviceExtraHeaders | toJson }}'
{{- end }}
{{- if eq .Values.mcpConfig.unique.serviceAuthMode "external" }}
UNIQUE_ZITADEL_CLIENT_ID: {{ .Values.mcpConfig.unique.zitadel.clientId | quote }}
UNIQUE_ZITADEL_OAUTH_TOKEN_URL: {{ .Values.mcpConfig.unique.zitadel.oauthTokenUrl | quote }}
UNIQUE_ZITADEL_PROJECT_ID: {{ .Values.mcpConfig.unique.zitadel.projectId | quote }}
{{- end }}
{{- end }}
