{{/* mcp-scaffold-commit: 5264f9f14505, timestamp: 2026-11-02T00:13:01+00:00 */}}
{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
mcpConfig environment variables: non-secret fields with tenant-specific values.
Secrets (ZITADEL_JWT_SIGNING_KEY, ENCRYPTION_KEY) stay in envVars or secret refs.
*/}}
{{- define "chart.config.mcpEnv" -}}
{{- if .Values.mcpConfig.app.publicBaseUrl }}
- name: UNIQUE_MCP_PUBLIC_BASE_URL
  value: {{ tpl .Values.mcpConfig.app.publicBaseUrl . | quote }}
{{- end }}
{{- if .Values.mcpConfig.zitadel.baseUrl }}
- name: ZITADEL_BASE_URL
  value: {{ tpl .Values.mcpConfig.zitadel.baseUrl . | quote }}
{{- end }}
{{- if .Values.mcpConfig.zitadel.clientId }}
- name: ZITADEL_CLIENT_ID
  value: {{ tpl .Values.mcpConfig.zitadel.clientId . | quote }}
{{- end }}
{{- end -}}
