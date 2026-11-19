{{- define "base.deployment.container.app.env.ext" -}}
{{- if .Values.mcpConfig.enabled }}
{{- include "chart.config.mcpEnv" . }}
{{- end }}
{{- end -}}

{{/*
Zitadel's hostname is usually multi-label (e.g. id.<tenant>.unique.app), which the
baseline "*.unique.app" toFQDNs matchPattern does not cover (Cilium's "*" does not
match "."). Derive an exact matchName from mcpConfig.zitadel.baseUrl so enabling
networkPolicy does not silently drop the Zitadel calls this chart requires.
*/}}
{{- define "base.externalService.networkPolicy.cilium.egress.rules.ext" -}}
{{- if and .Values.mcpConfig.enabled .Values.mcpConfig.zitadel.baseUrl -}}
{{- $zitadelHost := (tpl .Values.mcpConfig.zitadel.baseUrl . | urlParse).hostname -}}
- toFQDNs:
  - matchName: {{ $zitadelHost | quote }}
  toPorts:
  - ports:
    - port: "443"
      protocol: TCP
{{- end -}}
{{- end -}}

{{- define "base.externalService.networkPolicy.cilium.egress.hasRules.ext" -}}
{{- if and .Values.mcpConfig.enabled .Values.mcpConfig.zitadel.baseUrl -}}true{{- end -}}
{{- end -}}
