{{- define "chart.config.unique" -}}
{{- with .Values.mcpConfig.unique }}
- name: UNIQUE_SERVICE_AUTH_MODE
  value: {{ .serviceAuthMode | quote }}
- name: UNIQUE_INGESTION_SERVICE_BASE_URL
  value: {{ include "chart.ensureNoTrailingSlash" (dict "url" (tpl .ingestionServiceBaseUrl $)) | quote }}
- name: UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL
  value: {{ include "chart.ensureNoTrailingSlash" (dict "url" (tpl .scopeManagementServiceBaseUrl $)) | quote }}
{{- if .storeInternally }}
- name: UNIQUE_STORE_INTERNALLY
  value: {{ .storeInternally | quote }}
{{- end }}
{{- if eq .serviceAuthMode "cluster_local" }}
- name: UNIQUE_SERVICE_EXTRA_HEADERS
  value: {{ .serviceExtraHeaders | toJson | quote }}
{{- end }}
{{- if eq .serviceAuthMode "external" }}
- name: UNIQUE_ZITADEL_CLIENT_ID
  value: {{ tpl .zitadel.clientId $ | quote }}
- name: UNIQUE_ZITADEL_OAUTH_TOKEN_URL
  value: {{ tpl .zitadel.oauthTokenUrl $ | quote }}
- name: UNIQUE_ZITADEL_PROJECT_ID
  value: {{ tpl .zitadel.projectId $ | quote }}
{{- end }}
{{- end }}
{{- end }}
