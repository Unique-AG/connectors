{{ template "chart.header" . }}

{{ template "chart.description" . }}

{{ template "chart.homepageLine" . }}

{{ template "chart.maintainersSection" . }}

{{ template "chart.sourcesSection" . }}

{{ template "chart.requirementsSection" . }}

## Installation

### Requirements

You need to install [`aslafy-z/helm-git`](https://github.com/aslafy-z/helm-git). OCI registry based installation options will be provided in a future release.

### Helm

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```bash
helm repo add cfc git+https://github.com/Unique-AG/connectors@services/confluence-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
helm template cfc/confluence-connector --version <v-less-version-only>
```

### [`helmfile`](https://helmfile.readthedocs.io)

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```yaml
# helmfile version v1.1.7
repositories:
  - name: cfc
    url: git+https://github.com/Unique-AG/connectors@services/confluence-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
releases:
  - name: confluence-connector
    chart: cfc/confluence-connector
    version: <v-less-version-only>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)
```yaml
spec:
  name: confluence-connector
  …
  sources:
    - repoURL: https://github.com/Unique-AG/connectors.git
      path: services/confluence-connector/deploy/helm-charts/confluence-connector
      targetRevision: <release-tag>
```


{{ template "chart.valuesSection" . }}

{{ template "helm-docs.versionFooter" . }}
