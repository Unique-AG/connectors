{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
mcpConfig as container env vars. A list renders even when [], since an empty markers variable
replaces the app default; null leaves it unset.
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
{{- if .Values.mcpConfig.tenantGuidance }}
- name: BACKSTOP_MCP_TENANT_GUIDANCE
  value: {{ toJson .Values.mcpConfig.tenantGuidance | quote }}
{{- end }}
{{- end -}}
