{{- define "chart.config.ingestion" -}}
{{- /* MCP_BACKEND is declared in _config-app.tpl */ -}}
{{- with .Values.mcpConfig }}
{{- if .ingestion }}
- name: INGESTION_DEFAULT_MAIL_FILTERS
  value: {{ .ingestion.defaultMailFilters | toJson | quote }}
{{- if .ingestion.liveCatchupOverlappingWindowMinutes }}
- name: INGESTION_LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES
  value: {{ .ingestion.liveCatchupOverlappingWindowMinutes | quote }}
{{- end }}
{{- if .ingestion.liveCatchupRecheckOverlappingWindowMinutes }}
- name: INGESTION_LIVE_CATCHUP_RECHECK_OVERLAPPING_WINDOW_MINUTES
  value: {{ .ingestion.liveCatchupRecheckOverlappingWindowMinutes | quote }}
{{- end }}
{{- if .ingestion.fullSyncRecoveryCron }}
- name: INGESTION_FULL_SYNC_RECOVERY_CRON
  value: {{ .ingestion.fullSyncRecoveryCron | quote }}
{{- end }}
{{- if .ingestion.liveCatchupRecoveryCron }}
- name: INGESTION_LIVE_CATCHUP_RECOVERY_CRON
  value: {{ .ingestion.liveCatchupRecoveryCron | quote }}
{{- end }}
{{- if .ingestion.liveCatchupOauthUsersRecheckCron }}
- name: INGESTION_LIVE_CATCHUP_OAUTH_USERS_RECHECK_CRON
  value: {{ .ingestion.liveCatchupOauthUsersRecheckCron | quote }}
{{- end }}
{{- if .ingestion.liveCatchupSharedMailboxRecheckCron }}
- name: INGESTION_LIVE_CATCHUP_SHARED_MAILBOX_RECHECK_CRON
  value: {{ .ingestion.liveCatchupSharedMailboxRecheckCron | quote }}
{{- end }}
{{- if .ingestion.deleteInboxRecoveryCron }}
- name: INGESTION_DELETE_INBOX_RECOVERY_CRON
  value: {{ .ingestion.deleteInboxRecoveryCron | quote }}
{{- end }}
{{- if (hasKey .ingestion "connectivityTimeoutMs") }}
- name: INGESTION_CONNECTIVITY_TIMEOUT_MS
  value: {{ .ingestion.connectivityTimeoutMs | quote }}
{{- end }}
{{- if (hasKey .ingestion "syncFailureThreshold") }}
- name: INGESTION_SYNC_FAILURE_THRESHOLD
  value: {{ .ingestion.syncFailureThreshold | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
