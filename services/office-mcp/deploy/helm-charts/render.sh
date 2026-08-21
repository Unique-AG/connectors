#!/bin/bash
# Local helper to quick-render the chart locally to see its output.
# ci-values.yaml supplies the placeholder PUBLIC_BASE_URL that office-mcp.validateValues
# demands and drops the Postgres connection the values schema demands. CI passes the same
# file, so chart defaults alone never render.
helm template \
    office-mcp \
    office-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace office-mcp \
    --values office-mcp/ci-values.yaml
