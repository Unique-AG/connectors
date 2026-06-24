#!/usr/bin/env bash
# render-values-schema.sh — pull the base library schema from OCI and deep-merge
# with each chart's values.additional.schema.json to produce values.schema.json.
#
# Usage:
#   scripts/render-values-schema.sh [--check]
#
#   --check  Verify that the committed values.schema.json matches what would be
#            generated. Exits 1 on drift (suitable for CI).
#
# Requirements:
#   - helm (with OCI push/pull support)
#   - jq  (>= 1.6)
#   - GHCR login: helm registry login ghcr.io -u <user> -p <token>
set -euo pipefail

CHECK_MODE=false
if [[ "${1:-}" == "--check" ]]; then
  CHECK_MODE=true
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIRS=(
  "services/confluence-connector/deploy/helm-charts/confluence-connector"
  "services/sharepoint-connector/deploy/helm-charts/sharepoint-connector"
  "services/teams-mcp/deploy/helm-charts/teams-mcp"
  "services/outlook-semantic-mcp/deploy/helm-charts/outlook-semantic-mcp"
)

had_drift=false

for chart_dir in "${CHART_DIRS[@]}"; do
  abs_dir="${REPO_ROOT}/${chart_dir}"
  chart_yaml="${abs_dir}/Chart.yaml"
  additional_schema="${abs_dir}/values.additional.schema.json"
  target_schema="${abs_dir}/values.schema.json"

  if [[ ! -f "${chart_yaml}" ]]; then
    echo "SKIP: ${chart_dir} — Chart.yaml not found" >&2
    continue
  fi

  if [[ ! -f "${additional_schema}" ]]; then
    echo "SKIP: ${chart_dir} — values.additional.schema.json not found" >&2
    continue
  fi

  # Parse base chart version from Chart.yaml
  base_version=$(grep -A3 'name: base' "${chart_yaml}" | grep 'version:' | head -1 | awk '{print $2}')
  if [[ -z "${base_version}" ]]; then
    echo "ERROR: ${chart_dir} — could not determine base chart version from Chart.yaml" >&2
    exit 1
  fi

  echo "Processing ${chart_dir} (base version: ${base_version})"

  # Pull the base chart and extract its values.schema.json.
  # helm pull --untar is used instead of helm show schema because the latter
  # does not reliably support the --version flag for OCI registries across
  # Helm versions (fails silently in Helm 3.x with some OCI endpoints).
  base_tmpdir=$(mktemp -d)
  if ! helm pull "oci://ghcr.io/unique-ag/helm/base" --version "${base_version}" --untar -d "${base_tmpdir}" 2>/dev/null; then
    echo "ERROR: ${chart_dir} — failed to pull base chart version ${base_version}" >&2
    rm -rf "${base_tmpdir}"
    exit 1
  fi
  base_schema_file="${base_tmpdir}/base/values.schema.json"
  if [[ ! -f "${base_schema_file}" ]]; then
    echo "ERROR: ${chart_dir} — values.schema.json not found in pulled base chart" >&2
    rm -rf "${base_tmpdir}"
    exit 1
  fi
  base_schema_json=$(cat "${base_schema_file}")
  rm -rf "${base_tmpdir}"

  # Deep-merge base schema with chart-specific additional schema.
  # Strategy:
  #   - Start with the base schema (provides all base chart properties + $schema, additionalProperties)
  #   - Override title and description from the additional schema when present
  #   - Merge the additional schema's "properties" into the base schema's "properties"
  merged_schema=$(jq -s '
    .[0] as $base |
    .[1] as $extra |
    $base * {
      "title": ($extra.title // $base.title),
      "description": ($extra.description // $base.description),
      "properties": ($base.properties + $extra.properties)
    }
  ' <(echo "${base_schema_json}") "${additional_schema}")

  if [[ "${CHECK_MODE}" == "true" ]]; then
    committed=$(cat "${target_schema}")
    generated=$(echo "${merged_schema}" | jq --sort-keys .)
    committed_sorted=$(echo "${committed}" | jq --sort-keys .)
    if [[ "${generated}" != "${committed_sorted}" ]]; then
      echo "DRIFT: ${chart_dir} — values.schema.json is out of date. Run scripts/render-values-schema.sh to regenerate." >&2
      had_drift=true
    else
      echo "  OK: ${chart_dir}"
    fi
  else
    echo "${merged_schema}" | jq . > "${target_schema}"
    echo "  Written: ${target_schema}"
  fi
done

if [[ "${had_drift}" == "true" ]]; then
  exit 1
fi
