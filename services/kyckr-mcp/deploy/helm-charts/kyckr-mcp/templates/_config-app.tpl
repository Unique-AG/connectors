{{- define "chart.config.app" -}}
{{- with .Values.mcpConfig }}
{{- if .app.bufferLogs }}
APP_BUFFER_LOGS: {{ .app.bufferLogs | quote }}
{{- end }}
{{- end }}
{{- end }}
