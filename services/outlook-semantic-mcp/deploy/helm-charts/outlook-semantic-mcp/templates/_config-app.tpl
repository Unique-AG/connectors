{{- define "chart.config.app" -}}
{{- with .Values.mcpConfig }}
SELF_URL: {{ .app.selfUrl | quote }}
DEFAULT_MAIL_FILTERS: {{ .defaultMailFilters | quote }}
MCP_DEBUG_MODE: {{ .app.mcpDebugMode | quote }}
{{- if .app.bufferLogs }}
APP_BUFFER_LOGS: {{ .app.bufferLogs | quote }}
LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES: {{ .app.liveCatchupOverlappingWindowMinutes | quote }}
{{- end }}
{{- end }}
{{- end }}
