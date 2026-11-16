#!/usr/bin/env bash
# Renders the chart's custom alert rules and runs the promtool rule tests against them.
# Needs helm, yq and promtool on PATH, and the chart dependencies built (helm dependency build).
set -euo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chart_dir="$tests_dir/../helm-charts/confluence-connector"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

helm template confluence-connector "$chart_dir" \
  --values "$chart_dir/ci-values.yaml" \
  --api-versions monitoring.coreos.com/v1 |
  yq 'select(.kind == "PrometheusRule" and .metadata.name == "*-custom-alerts") | .spec' \
    >"$work_dir/rendered-rules.yaml"
promtool check rules "$work_dir/rendered-rules.yaml"

# The tests check when alerts fire. Without annotations they need not repeat every runbook.
yq 'del(.groups[].rules[].annotations)' "$work_dir/rendered-rules.yaml" >"$work_dir/rules.yaml"
cp "$tests_dir"/*.test.yaml "$work_dir/"
promtool test rules "$work_dir"/*.test.yaml
