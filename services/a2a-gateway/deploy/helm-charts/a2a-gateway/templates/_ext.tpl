{{- define "base.deployment.container.app.env.ext" -}}
{{- include "chart.config.amqpUrl" . }}
{{- if .Values.a2aConfig.enabled }}
{{ include "chart.config.a2aEnv" . }}
{{- end }}
{{- end -}}

{{- define "base.externalService.networkPolicy.cilium.egress.rules.ext" -}}
{{- include "chart.networkPolicy.egressHosts" . }}
{{- end -}}

{{- define "base.externalService.networkPolicy.cilium.egress.hasRules.ext" -}}
{{- if include "chart.networkPolicy.egressHosts" . | trim }}true{{- end }}
{{- end -}}
