{{- define "chart.config.app" -}}
{{- with .Values.mcpConfig }}
- name: SELF_URL
  value: {{ tpl .app.selfUrl $ | quote }}
- name: MCP_DEBUG_MODE
  value: {{ .app.mcpDebugMode | quote }}
- name: MCP_BACKEND
  value: {{ .app.mcpBackend | quote }}
{{- if .app.directorySyncCronSchedule }}
- name: DIRECTORY_SYNC_CRON_SCHEDULE
  value: {{ .app.directorySyncCronSchedule | quote }}
{{- end }}
{{- if .app.logsBuffering }}
- name: LOGS_BUFFERING
  value: {{ .app.logsBuffering | quote }}
{{- end }}
{{- if .app.logsDiagnosticsDataPolicy }}
- name: LOGS_DIAGNOSTICS_DATA_POLICY
  value: {{ .app.logsDiagnosticsDataPolicy | quote }}
{{- end }}
{{- end }}
{{- end }}
