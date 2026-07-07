{{- define "base.deployment.container.app.env.ext" -}}
{{- if .Values.mcpConfig.enabled }}
{{- include "chart.config.app" . }}
{{- include "chart.config.delegatedAccess" . }}
{{- include "chart.config.ingestion" . }}
{{- include "chart.config.auth" . }}
{{- include "chart.config.microsoft" . }}
{{- include "chart.config.unique" . }}
{{- end }}
{{- end -}}

{{- define "base.hookJob.container.app.env.ext" -}}
{{- if .Values.mcpConfig.enabled }}
{{- include "chart.config.app" . }}
{{- include "chart.config.delegatedAccess" . }}
{{- include "chart.config.ingestion" . }}
{{- include "chart.config.auth" . }}
{{- include "chart.config.microsoft" . }}
{{- include "chart.config.unique" . }}
{{- end }}
{{- end -}}
