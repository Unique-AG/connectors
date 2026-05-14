{{- define "chart.config.ingestion" -}}
{{- /* MCP_BACKEND is declared in _config-app.tpl */ -}}
{{- with .Values.mcpConfig }}
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
{{- if .ingestion.liveCatchupRecoveryCron }}
INGESTION_LIVE_CATCHUP_RECOVERY_CRON: {{ .ingestion.liveCatchupRecoveryCron | quote }}
{{- end }}
{{- if .ingestion.deleteInboxRecoveryCron }}
INGESTION_DELETE_INBOX_RECOVERY_CRON: {{ .ingestion.deleteInboxRecoveryCron | quote }}
{{- end }}
{{- if (hasKey .ingestion "connectivityTimeoutMs") }}
INGESTION_CONNECTIVITY_TIMEOUT_MS: {{ .ingestion.connectivityTimeoutMs | quote }}
{{- end }}
{{- if (hasKey .ingestion "syncFailureThreshold") }}
INGESTION_SYNC_FAILURE_THRESHOLD: {{ .ingestion.syncFailureThreshold | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
