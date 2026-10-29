{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
mcpConfig as container env vars. A list renders even when [], since an empty markers or
redirect-allowlist variable replaces the app default; null leaves it unset.
*/}}
{{- define "chart.config.mcpEnv" -}}
{{- if .Values.mcpConfig.app.publicBaseUrl }}
- name: PUBLIC_BASE_URL
  value: {{ tpl .Values.mcpConfig.app.publicBaseUrl . | quote }}
{{- end }}
{{- if .Values.mcpConfig.backstop.baseUrl }}
- name: BACKSTOP_BASE_URL
  value: {{ tpl .Values.mcpConfig.backstop.baseUrl . | quote }}
{{- end }}
{{- if .Values.mcpConfig.backstop.uiBaseUrl }}
- name: BACKSTOP_UI_BASE_URL
  value: {{ tpl .Values.mcpConfig.backstop.uiBaseUrl . | quote }}
{{- end }}
{{- $employment := .Values.mcpConfig.employment | default dict }}
{{- $employmentEnv := list
  (list "relationshipTypeIds" "BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS")
  (list "relationshipTypeMarkers" "BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS")
  (list "formerRelationshipTypeIds" "BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_IDS")
  (list "formerRelationshipTypeMarkers" "BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS")
}}
{{- range $pair := $employmentEnv }}
{{- $items := index $employment (first $pair) }}
{{- if not (kindIs "invalid" $items) }}
- name: {{ last $pair }}
  value: {{ join "," $items | quote }}
{{- end }}
{{- end }}
{{- $auth := .Values.mcpConfig.auth | default dict }}
{{- $authEnv := list
  (list "allowedRedirectHosts" "AUTH_ALLOWED_REDIRECT_HOSTS")
  (list "allowedRedirectSchemes" "AUTH_ALLOWED_REDIRECT_SCHEMES")
}}
{{- range $pair := $authEnv }}
{{- $items := index $auth (first $pair) }}
{{- if not (kindIs "invalid" $items) }}
- name: {{ last $pair }}
  value: {{ join "," $items | quote }}
{{- end }}
{{- end }}
{{- if .Values.mcpConfig.tenantGuidance }}
- name: BACKSTOP_MCP_TENANT_GUIDANCE
  value: {{ toJson .Values.mcpConfig.tenantGuidance | quote }}
{{- end }}
{{- $logging := .Values.mcpConfig.logging | default dict }}
{{- if $logging.level }}
- name: LOG_LEVEL
  value: {{ $logging.level | quote }}
{{- end }}
{{- if $logging.libraryLevels }}
- name: LIBRARY_LOG_LEVELS
  value: {{ toJson $logging.libraryLevels | quote }}
{{- end }}
{{- if $logging.diagnosticsDataPolicy }}
- name: LOGS_DIAGNOSTICS_DATA_POLICY
  value: {{ $logging.diagnosticsDataPolicy | quote }}
{{- end }}
{{- if $logging.errorDetailsPolicy }}
- name: ERROR_DETAILS_POLICY
  value: {{ $logging.errorDetailsPolicy | quote }}
{{- end }}
{{- end -}}
