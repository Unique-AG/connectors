{{- define "chart.config.delegatedAccess" -}}
{{- /* MCP_BACKEND is declared in _config-app.tpl */ -}}
{{- with .Values.mcpConfig }}
DELEGATED_ACCESS_SCAN: {{ .app.delegatedAccessScan | quote }}
{{- if .app.delegatedAccessDiscoveryCronSchedule }}
DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE: {{ .app.delegatedAccessDiscoveryCronSchedule | quote }}
{{- end }}
{{- if .app.delegatedAccessVerificationCronSchedule }}
DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE: {{ .app.delegatedAccessVerificationCronSchedule | quote }}
{{- end }}
{{- end }}
{{- end }}
