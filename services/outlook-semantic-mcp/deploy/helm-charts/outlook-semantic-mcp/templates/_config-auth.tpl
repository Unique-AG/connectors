{{- define "chart.config.auth" -}}
{{- if .Values.mcpConfig.auth.accessTokenExpiresInSeconds }}
AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS: {{ .Values.mcpConfig.auth.accessTokenExpiresInSeconds | quote }}
{{- end }}
{{- if .Values.mcpConfig.auth.refreshTokenExpiresInSeconds }}
AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS: {{ .Values.mcpConfig.auth.refreshTokenExpiresInSeconds | quote }}
{{- end }}
{{- end }}
