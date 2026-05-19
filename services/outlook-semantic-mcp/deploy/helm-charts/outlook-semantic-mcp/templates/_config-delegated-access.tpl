{{- define "chart.config.delegatedAccess" -}}
{{- /* MCP_BACKEND is declared in _config-app.tpl */ -}}
{{- with .Values.mcpConfig }}
{{- with .delegatedAccess }}
DELEGATED_ACCESS_SCAN: {{ .scan | quote }}
{{- if .discoveryCronSchedule }}
DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE: {{ .discoveryCronSchedule | quote }}
{{- end }}
{{- if .verificationCronSchedule }}
DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE: {{ .verificationCronSchedule | quote }}
{{- end }}
{{- if .recoveryCronSchedule }}
DELEGATED_ACCESS_RECOVERY_CRON_SCHEDULE: {{ .recoveryCronSchedule | quote }}
{{- end }}
{{- if (hasKey . "stalenessThresholdHours") }}
DELEGATED_ACCESS_STALENESS_THRESHOLD_HOURS: {{ .stalenessThresholdHours | quote }}
{{- end }}
{{- if (hasKey . "failureThreshold") }}
DELEGATED_ACCESS_FAILURE_THRESHOLD: {{ .failureThreshold | quote }}
{{- end }}
{{- if .sharedMailboxEmails }}
DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS: {{ .sharedMailboxEmails | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
