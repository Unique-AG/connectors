{{- define "chart.config.app" -}}
{{- with .Values.mcpConfig }}
SELF_URL: {{ .app.selfUrl | quote }}
MCP_DEBUG_MODE: {{ .app.mcpDebugMode | quote }}
MCP_BACKEND: {{ .app.mcpBackend | quote }}
DELEGATED_ACCESS_SCAN: {{ .app.delegatedAccessScan | quote }}
{{- if .app.bufferLogs }}
APP_BUFFER_LOGS: {{ .app.bufferLogs | quote }}
{{- end }}
{{- if .app.delegatedAccessDiscoveryCronSchedule }}
DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE: {{ .app.delegatedAccessDiscoveryCronSchedule | quote }}
{{- end }}
{{- if .app.delegatedAccessVerificationCronSchedule }}
DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE: {{ .app.delegatedAccessVerificationCronSchedule | quote }}
{{- end }}
{{- if .ingestion }}
INGESTION_DEFAULT_MAIL_FILTERS: {{ .ingestion.defaultMailFilters | toJson | quote }}
{{- if .ingestion.liveCatchupOverlappingWindowMinutes }}
INGESTION_LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES: {{ .ingestion.liveCatchupOverlappingWindowMinutes | quote }}
{{- end }}
{{- if .ingestion.liveCatchupRecheckOverlappingWindowMinutes }}
INGESTION_LIVE_CATCHUP_RECHECK_OVERLAPPING_WINDOW_MINUTES: {{ .ingestion.liveCatchupRecheckOverlappingWindowMinutes | quote }}
{{- end }}
{{- if .ingestion.fullSyncRecoveryCron }}
INGESTION_FULL_SYNC_RECOVERY_CRON: {{ .ingestion.fullSyncRecoveryCron | quote }}
{{- end }}
{{- if .ingestion.liveCatchupRecovery }}
INGESTION_LIVE_CATCHUP_RECOVERY: {{ .ingestion.liveCatchupRecovery | quote }}
{{- end }}
{{- if .ingestion.deleteInboxRecoveryCron }}
INGESTION_DELETE_INBOX_RECOVERY_CRON: {{ .ingestion.deleteInboxRecoveryCron | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
