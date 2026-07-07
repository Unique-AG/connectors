{{- define "chart.config.delegatedAccess" -}}
{{- /* MCP_BACKEND is declared in _config-app.tpl */ -}}
{{- with .Values.mcpConfig }}
{{- with .delegatedAccess }}
- name: DELEGATED_ACCESS_SCAN
  value: {{ .scan | quote }}
{{- if .discoveryCronSchedule }}
- name: DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE
  value: {{ .discoveryCronSchedule | quote }}
{{- end }}
{{- if .verificationCronSchedule }}
- name: DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE
  value: {{ .verificationCronSchedule | quote }}
{{- end }}
{{- if .recoveryCronSchedule }}
- name: DELEGATED_ACCESS_RECOVERY_CRON_SCHEDULE
  value: {{ .recoveryCronSchedule | quote }}
{{- end }}
{{- if (hasKey . "stalenessThresholdHours") }}
- name: DELEGATED_ACCESS_STALENESS_THRESHOLD_HOURS
  value: {{ .stalenessThresholdHours | quote }}
{{- end }}
{{- if (hasKey . "failureThreshold") }}
- name: DELEGATED_ACCESS_FAILURE_THRESHOLD
  value: {{ .failureThreshold | quote }}
{{- end }}
{{- if .sharedMailboxEmails }}
- name: DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS
  value: {{ .sharedMailboxEmails | quote }}
{{- end }}
{{- if .sharedMailboxSyncCronSchedule }}
- name: DELEGATED_ACCESS_SHARED_MAILBOX_SYNC_CRON_SCHEDULE
  value: {{ .sharedMailboxSyncCronSchedule | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
