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
