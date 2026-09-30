{{/*
Chart-specific helpers. Generic identity/label helpers are provided by the base library (base.fullname, base.labels.common, etc.).
*/}}

{{/*
All a2aConfig environment variables for the app container.
*/}}
{{- define "chart.config.a2aEnv" -}}
{{- if hasKey (.Values.env | default dict) "EGRESS_ALLOW_INSECURE" }}
{{- fail "EGRESS_ALLOW_INSECURE must not be set; the gateway refuses insecure egress in production." }}
{{- end }}
{{- $c := .Values.a2aConfig -}}
- name: PUBLIC_BASE_URL
  value: {{ tpl $c.publicBaseUrl . | quote }}
- name: ZITADEL_ISSUER
  value: {{ tpl $c.zitadelIssuer . | quote }}
- name: CORS_ALLOWED_ORIGINS
  value: {{ join "," $c.corsAllowedOrigins | quote }}
- name: UNIQUE_CHAT_URL
  value: {{ tpl $c.unique.chatUrl . | quote }}
- name: UNIQUE_SCOPE_MANAGEMENT_URL
  value: {{ tpl $c.unique.scopeManagementUrl . | quote }}
- name: UNIQUE_INGESTION_URL
  value: {{ tpl $c.unique.ingestionUrl . | quote }}
- name: EGRESS_ALLOWED_HOSTS
  value: {{ join "," $c.egress.allowedHosts | quote }}
- name: PUSH_NOTIFICATIONS_ENABLED
  value: {{ $c.pushNotifications.enabled | quote }}
- name: PUSH_ALLOWED_HOSTS
  value: {{ join "," $c.pushNotifications.allowedHosts | quote }}
- name: WORKER_ENABLED
  value: {{ $c.worker.enabled | quote }}
- name: WORKER_CONCURRENCY
  value: {{ $c.worker.concurrency | quote }}
- name: RECONCILE_INTERVAL
  value: {{ $c.reconcileIntervalSeconds | quote }}
- name: TASK_RETENTION_DAYS
  value: {{ $c.retention.taskDays | quote }}
- name: EXECUTION_RETENTION_DAYS
  value: {{ $c.retention.executionDays | quote }}
- name: MAX_REQUEST_BYTES
  value: {{ $c.limits.maxRequestBytes | int | quote }}
- name: MAX_REMOTE_FILE_BYTES
  value: {{ $c.limits.maxRemoteFileBytes | int | quote }}
- name: STREAM_TIMEOUT_MS
  value: {{ $c.limits.streamTimeoutMs | int | quote }}
- name: ELICITATION_TIMEOUT_SECONDS
  value: {{ $c.limits.elicitationTimeoutSeconds | quote }}
- name: MAX_ACTIVE_EXECUTIONS_PER_TENANT
  value: {{ $c.limits.maxActiveExecutionsPerTenant | quote }}
- name: MAX_ACTIVE_EXECUTIONS_PER_CONNECTION
  value: {{ $c.limits.maxActiveExecutionsPerConnection | quote }}
- name: MAX_ACTIVE_TASKS_PER_TENANT
  value: {{ $c.limits.maxActiveTasksPerTenant | quote }}
{{- end -}}

{{/*
AMQP_URL composed from the structured AMQP_* variables projected by the base chart.
URL mode (rabbitmq.connection.url) already projects AMQP_URL.
*/}}
{{- define "chart.config.amqpUrl" -}}
{{- $rmq := .Values.rabbitmq | default dict -}}
{{- $c := $rmq.connection | default dict -}}
{{- if and $rmq.enabled (not $c.url) }}
{{- if not (and $c.username $c.password) }}
{{- fail "rabbitmq.connection requires url, or username and password to compose AMQP_URL." }}
{{- end }}
- name: AMQP_URL
  value: {{ printf "amqp://$(AMQP_USERNAME):$(AMQP_PASSWORD)@$(AMQP_HOST):$(AMQP_PORT)%s" (ternary "/$(AMQP_VHOST)" "" (not (empty $c.vhost))) | quote }}
{{- end }}
{{- end -}}

{{/*
CiliumNetworkPolicy egress to the approved remote agents and push webhook hosts.
*/}}
{{- define "chart.networkPolicy.egressHosts" -}}
{{- $c := .Values.a2aConfig -}}
{{- $hosts := $c.egress.allowedHosts | default list -}}
{{- if $c.pushNotifications.enabled -}}
{{- $hosts = concat $hosts ($c.pushNotifications.allowedHosts | default list) -}}
{{- end -}}
{{- $hosts = $hosts | uniq | sortAlpha -}}
{{- if and $c.enabled $hosts }}
- toFQDNs:
  {{- range $hosts }}
  - matchName: {{ . | quote }}
  {{- end }}
  toPorts:
  - ports:
    {{- range $c.egress.ports }}
    - port: {{ . | toString | quote }}
      protocol: TCP
    {{- end }}
{{- end }}
{{- end -}}

{{/*
"true" when any Kong route of this chart is enabled; gates the KongPlugin resources.
*/}}
{{- define "chart.kong.enabled" -}}
{{- $routes := .Values.extraRoutes | default dict -}}
{{- if or ($routes.public).enabled ($routes.callbacks).enabled ($routes.protected).enabled }}true{{- end }}
{{- end -}}
