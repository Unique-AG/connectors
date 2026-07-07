{{- define "base.deployment.pod.volumes.ext" -}}
{{- if .Values.connectorConfig.enabled }}
- name: tenant-config
  configMap:
    name: {{ include "base.fullname" . }}-tenant-config
{{- end }}
{{- end -}}

{{- define "base.deployment.container.app.volumeMounts.ext" -}}
{{- if .Values.connectorConfig.enabled }}
- name: tenant-config
  mountPath: /app/tenant-configs
  readOnly: true
{{- end }}
{{- end -}}

{{- define "base.deployment.container.app.env.ext" -}}
{{- if .Values.proxyConfig.enabled }}
- name: PROXY_AUTH_MODE
  value: {{ .Values.proxyConfig.authMode | quote }}
{{- if ne .Values.proxyConfig.authMode "none" }}
- name: PROXY_HOST
  value: {{ .Values.proxyConfig.host | quote }}
- name: PROXY_PORT
  value: {{ .Values.proxyConfig.port | quote }}
- name: PROXY_PROTOCOL
  value: {{ .Values.proxyConfig.protocol | quote }}
{{- end }}
{{- if eq .Values.proxyConfig.authMode "username_password" }}
- name: PROXY_USERNAME
  value: {{ .Values.proxyConfig.username | quote }}
{{- end }}
{{- if eq .Values.proxyConfig.authMode "ssl_tls" }}
- name: PROXY_SSL_CERT_PATH
  value: {{ .Values.proxyConfig.sslCertPath | quote }}
- name: PROXY_SSL_KEY_PATH
  value: {{ .Values.proxyConfig.sslKeyPath | quote }}
{{- end }}
{{- if .Values.proxyConfig.sslCaBundlePath }}
- name: PROXY_SSL_CA_BUNDLE_PATH
  value: {{ .Values.proxyConfig.sslCaBundlePath | quote }}
{{- end }}
{{- if .Values.proxyConfig.headers }}
- name: PROXY_HEADERS
  value: {{ .Values.proxyConfig.headers | quote }}
{{- end }}
{{- end }}
{{- end -}}
