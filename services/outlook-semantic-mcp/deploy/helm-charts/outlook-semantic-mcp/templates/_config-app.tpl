{{- define "chart.config.app" -}}
SELF_URL: {{ .Values.mcpConfig.app.selfUrl | quote }}
DEFAULT_MAIL_FILTERS: {{ .Values.mcpConfig.defaultMailFilters | quote }}
{{- if .Values.mcpConfig.app.mcpDebugMode }}
MCP_DEBUG_MODE: {{ .Values.mcpConfig.app.mcpDebugMode | quote }}
{{- end }}
{{- if .Values.mcpConfig.app.bufferLogs }}
BUFFER_LOGS: {{ .Values.mcpConfig.app.bufferLogs | quote }}
{{- end }}
{{- end }}
