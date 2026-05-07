{{- define "chart.config.app" -}}
{{- with .Values.mcpConfig }}
SELF_URL: {{ .app.selfUrl | quote }}
MCP_DEBUG_MODE: {{ .app.mcpDebugMode | quote }}
MCP_BACKEND: {{ .app.mcpBackend | quote }}
{{- if .app.bufferLogs }}
APP_BUFFER_LOGS: {{ .app.bufferLogs | quote }}
{{- end }}
{{- end }}
{{- end }}
