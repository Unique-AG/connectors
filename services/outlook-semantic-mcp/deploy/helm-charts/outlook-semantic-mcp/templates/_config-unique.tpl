{{- define "chart.config.unique" -}}
{{- with .Values.mcpConfig.unique }}
UNIQUE_SERVICE_AUTH_MODE: {{ .serviceAuthMode | quote }}
UNIQUE_INGESTION_SERVICE_BASE_URL: {{ include "chart.ensureNoTrailingSlash" (dict "url" .ingestionServiceBaseUrl) | quote }}
UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL: {{ include "chart.ensureNoTrailingSlash" (dict "url" .scopeManagementServiceBaseUrl) | quote }}
{{- if .storeInternally }}
UNIQUE_STORE_INTERNALLY: {{ .storeInternally | quote }}
{{- end }}
{{- if eq .serviceAuthMode "cluster_local" }}
UNIQUE_SERVICE_EXTRA_HEADERS: '{{ .serviceExtraHeaders | toJson }}'
{{- end }}
{{- if eq .serviceAuthMode "external" }}
UNIQUE_ZITADEL_CLIENT_ID: {{ .zitadel.clientId | quote }}
UNIQUE_ZITADEL_OAUTH_TOKEN_URL: {{ .zitadel.oauthTokenUrl | quote }}
UNIQUE_ZITADEL_PROJECT_ID: {{ .zitadel.projectId | quote }}
{{- end }}
{{- end }}
{{- end }}
