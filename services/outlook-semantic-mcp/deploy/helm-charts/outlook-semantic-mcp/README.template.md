{{ template "chart.header" . }}

{{ template "chart.description" . }}

{{ template "chart.homepageLine" . }}

{{ template "chart.maintainersSection" . }}

{{ template "chart.sourcesSection" . }}

{{ template "chart.requirementsSection" . }}

## Installation

Use OCI charts only. Prefer `getunique.azurecr.io`; `uniquecr.azurecr.io` is private and kept for consistency, and GHCR is maintained best-effort.

- `oci://getunique.azurecr.io/helm/outlook-semantic-mcp`
- `oci://uniquecr.azurecr.io/connectors/helm/outlook-semantic-mcp`
- `oci://ghcr.io/unique-ag/connectors/helm/outlook-semantic-mcp`

### Helm

```bash
helm template outlook-semantic-mcp \
  oci://getunique.azurecr.io/helm/outlook-semantic-mcp \
  --version <version>
```

### [`helmfile`](https://helmfile.readthedocs.io)

```yaml
# helmfile version v1.1.7
releases:
  - name: outlook-semantic-mcp
    chart: oci://getunique.azurecr.io/helm/outlook-semantic-mcp
    version: <version>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)

Pin the chart by OCI digest in GitOps. Keep the version as a comment for humans.

```yaml
spec:
  name: outlook-semantic-mcp
  sources:
    - repoURL: oci://getunique.azurecr.io/helm/outlook-semantic-mcp
      path: .
      targetRevision: sha256:<chart-digest> # <version>
```


{{ template "chart.valuesSection" . }}

{{ template "helm-docs.versionFooter" . }}
