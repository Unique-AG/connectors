{{- define "base.deployment.container.app.env.ext" -}}
{{- include "chart.config.mcpEnv" . }}
{{- end -}}

{{- define "base.externalService.secretProvider.collectExtByVault.ext" -}}
{{- include "base.conn.secretProvider.fields" (dict "extByVault" .extByVault "fields" (list .ctx.Values.mcpConfig.app.apiKey .ctx.Values.mcpConfig.kyckr.apiKey)) }}
{{- end -}}
