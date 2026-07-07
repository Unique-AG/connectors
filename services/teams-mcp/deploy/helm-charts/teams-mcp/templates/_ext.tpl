{{- define "base.deployment.container.app.env.ext" -}}
{{- if .Values.mcpConfig.enabled }}
{{- include "chart.config.mcpEnv" . }}
{{- end }}
{{- end -}}

{{- define "base.hookJob.container.app.env.ext" -}}
{{- if .Values.mcpConfig.enabled }}
{{- include "chart.config.mcpEnv" . }}
{{- end }}
{{- end -}}
