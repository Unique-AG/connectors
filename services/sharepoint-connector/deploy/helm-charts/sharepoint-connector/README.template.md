{{ template "chart.header" . }}

{{ template "chart.description" . }}

{{ template "chart.homepageLine" . }}

{{ template "chart.maintainersSection" . }}

{{ template "chart.sourcesSection" . }}

{{ template "chart.requirementsSection" . }}

## Installation

Until `2.0.0`, the chart can only be installed via 

### Requirements

You need to install [`aslafy-z/helm-git`](https://github.com/aslafy-z/helm-git). OCI registry based installation options will be provided with `2.0.0` onwards.

### Helm

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```bash
helm repo add spc git+https://github.com/Unique-AG/connectors@services/sharepoint-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
helm template spc/sharepoint-connector --version <v-less-version-only>
```

### [`helmfile`](https://helmfile.readthedocs.io)

> [!IMPORTANT]
> `<v-less-version-only>` means just the SemVer version.

```yaml
# helmfile version v1.1.7
repositories:
  - name: spc
    url: git+https://github.com/Unique-AG/connectors@services/sharepoint-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
releases:
  - name: sharepoint-connector
    chart: spc/sharepoint-connector
    version: <v-less-version-only>
```

### [Argo Application](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification)
```yaml
spec:
  name: sharepoint-connector
  …
  sources:
    - repoURL: https://github.com/Unique-AG/connectors.git
      path: services/sharepoint-connector/deploy/helm-charts/sharepoint-connector
      targetRevision: <release-tag>
```


{{ template "chart.valuesSection" . }}

{{ template "helm-docs.versionFooter" . }}
