{{- define "chart.config.log" -}}
{{- with .Values.mcpConfig.log }}
{{- if .buffering }}
LOG_BUFFERING: {{ .buffering | quote }}
{{- end }}
{{- if .diagnosticsDataPolicy }}
LOG_DIAGNOSTICS_DATA_POLICY: {{ .diagnosticsDataPolicy | quote }}
{{- end }}
{{- end }}
{{- end }}
