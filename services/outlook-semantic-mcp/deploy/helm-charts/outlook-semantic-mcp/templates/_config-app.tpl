{{- define "chart.config.app" -}}
{{- with .Values.mcpConfig }}
SELF_URL: {{ .app.selfUrl | quote }}
MCP_DEBUG_MODE: {{ .app.mcpDebugMode | quote }}
MCP_BACKEND: {{ .app.mcpBackend | quote }}
{{- if .app.directorySyncCronSchedule }}
DIRECTORY_SYNC_CRON_SCHEDULE: {{ .app.directorySyncCronSchedule | quote }}
{{- end }}
{{- end }}
{{- end }}
