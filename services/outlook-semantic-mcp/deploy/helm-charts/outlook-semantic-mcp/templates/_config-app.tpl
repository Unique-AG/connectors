{{- define "chart.config.app" -}}
{{- with .Values.mcpConfig }}
- name: SELF_URL
  value: {{ tpl .app.selfUrl $ | quote }}
- name: MCP_DEBUG_MODE
  value: {{ .app.mcpDebugMode | quote }}
- name: MCP_BACKEND
  value: {{ .app.mcpBackend | quote }}
{{- if empty .app.tools }}
{{- fail "mcpConfig.app.tools is mandatory: list the tools to register, e.g. [search_emails, open_email]." }}
{{- end }}
- name: MCP_TOOLS
  value: {{ toJson .app.tools | quote }}
{{- if eq .app.directorySyncMode "on_demand" }}
{{- if ne .app.mcpBackend "microsoft_graph" }}
{{- fail "mcpConfig.app.directorySyncMode on_demand needs mcpConfig.app.mcpBackend microsoft_graph: ingestion syncs the folders itself." }}
{{- end }}
{{- if ne .delegatedAccess.scan "disabled" }}
{{- fail "mcpConfig.app.directorySyncMode on_demand needs mcpConfig.delegatedAccess.scan disabled: only the scheduled sync refreshes shared mailbox folders." }}
{{- end }}
{{- end }}
- name: DIRECTORY_SYNC_MODE
  value: {{ .app.directorySyncMode | quote }}
{{- with .app.excludedSensitivity }}
{{- if and (or .labels .legacy) (ne $.Values.mcpConfig.app.mcpBackend "microsoft_graph") }}
{{- fail "mcpConfig.app.excludedSensitivity needs mcpConfig.app.mcpBackend microsoft_graph: semantic search results cannot be filtered by sensitivity." }}
{{- end }}
{{- if .labels }}
- name: EXCLUDED_SENSITIVITY_LABELS
  value: {{ toJson .labels | quote }}
{{- end }}
{{- if .legacy }}
- name: EXCLUDED_LEGACY_SENSITIVITY
  value: {{ toJson .legacy | quote }}
{{- end }}
{{- end }}
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
