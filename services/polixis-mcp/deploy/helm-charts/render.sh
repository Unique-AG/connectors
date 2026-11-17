#!/bin/bash
# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00
# Local helper to quick-render the chart locally to see its output.
# The chart defaults leave out the Postgres connection the values schema demands, so this passes
# ci-values.yaml, the same file CI renders with.
helm template \
    polixis-mcp \
    polixis-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace polixis-mcp \
    --values polixis-mcp/ci-values.yaml
