{{ template "chart.header" . }}

{{ template "chart.description" . }}

{{ template "chart.homepageLine" . }}

{{ template "chart.maintainersSection" . }}

{{ template "chart.sourcesSection" . }}

{{ template "chart.requirementsSection" . }}

## Installation

Use OCI charts only. Prefer `getunique.azurecr.io`; `uniquecr.azurecr.io` is private and kept for consistency, and GHCR is maintained best-effort.

- `oci://getunique.azurecr.io/helm/teams-mcp`
- `oci://uniquecr.azurecr.io/connectors/helm/teams-mcp`
- `oci://ghcr.io/unique-ag/connectors/helm/teams-mcp`

### Helm

```bash
helm template teams-mcp \
  oci://getunique.azurecr.io/helm/teams-mcp \
  --version <version>
```

### [`helmfile`](https://helmfile.readthedocs.io)

```yaml
# helmfile version v1.1.7
releases:
  - name: teams-mcp
    chart: oci://getunique.azurecr.io/helm/teams-mcp
    version: <version>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)

Pin the chart by OCI digest in GitOps. Keep the version as a comment for humans.

```yaml
spec:
  name: teams-mcp
  sources:
    - repoURL: oci://getunique.azurecr.io/helm/teams-mcp
      path: .
      targetRevision: sha256:<chart-digest> # <version>
```


{{ template "chart.valuesSection" . }}

{{ template "helm-docs.versionFooter" . }}
