{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
mcpConfig environment variables: non-secret fields with tenant-specific values.
Secrets stay in envVars or secret refs.

A list is rendered whenever it is set, even to []: setting a markers variable replaces the app's
default markers, so an empty list has to reach the app as an empty string rather than be dropped.
null (the default) leaves the variable unset.
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
{{- $employmentEnv := dict
  "relationshipTypeIds" "BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS"
  "relationshipTypeMarkers" "BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS"
  "formerRelationshipTypeIds" "BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_IDS"
  "formerRelationshipTypeMarkers" "BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS"
}}
{{- range $field, $name := $employmentEnv }}
{{- $items := index $employment $field }}
{{- if not (kindIs "invalid" $items) }}
- name: {{ $name }}
  value: {{ join "," $items | quote }}
{{- end }}
{{- end }}
{{/* Top-level tenantGuidance is deprecated and read only while mcpConfig.tenantGuidance is empty. */}}
{{- $guidance := .Values.mcpConfig.tenantGuidance | default .Values.tenantGuidance }}
{{- if $guidance }}
- name: BACKSTOP_MCP_TENANT_GUIDANCE
  value: {{ toJson $guidance | quote }}
{{- end }}
{{- end -}}
