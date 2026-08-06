{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
mcpConfig environment variables — only the non-secret fields with tenant-specific
values. Secrets (ZITADEL_CLIENT_ID/SECRET, UNIQUE_APP_*) stay out of values.yaml;
deliver those via envVars/secretKeyRef or the overlay's external-secrets.
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
{{- end -}}
