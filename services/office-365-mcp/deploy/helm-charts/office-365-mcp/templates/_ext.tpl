{{- define "base.deployment.container.app.env.ext" -}}
{{- include "chart.config.mcpEnv" . }}
{{- end -}}

{{/*
Registers mcpConfig.entra.clientSecret's fromSecretProvider (if used) into the SecretProviderClass
aggregator, so a deployment using it needs no separate secretProvider.vaults entry.
*/}}
{{- define "base.externalService.secretProvider.collectExtByVault.ext" -}}
{{- include "base.conn.secretProvider.fields" (dict "extByVault" .extByVault "fields" (list .ctx.Values.mcpConfig.entra.clientSecret)) }}
{{- end -}}
