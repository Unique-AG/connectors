{{- define "base.deployment.container.app.env.ext" -}}
{{- include "chart.config.mcpEnv" . }}
{{- end -}}

{{/* Cilium "*" does not match ".", so multi-label hosts get an exact matchName. */}}
{{- define "base.externalService.networkPolicy.cilium.egress.rules.ext" -}}
{{- range (include "chart.egressHosts" . | fromJsonArray) }}
- toFQDNs:
  - matchName: {{ . | quote }}
  toPorts:
  - ports:
    - port: "443"
      protocol: TCP
{{- end }}
{{- end -}}

{{- define "base.externalService.networkPolicy.cilium.egress.hasRules.ext" -}}
{{- if include "chart.egressHosts" . | fromJsonArray -}}true{{- end -}}
{{- end -}}
