{{- define "chart.config.app" -}}
SELF_URL: {{ .Values.mcpConfig.app.selfUrl | quote }}
DEFAULT_MAIL_FILTERS: {{ .Values.mcpConfig.defaultMailFilters | quote }}
MCP_DEBUG_MODE: {{ .Values.mcpConfig.app.mcpDebugMode | quote }}
{{- if .Values.mcpConfig.app.bufferLogs }}
APP_BUFFER_LOGS: {{ .Values.mcpConfig.app.bufferLogs | quote }}
{{- end }}
{{- end }}
