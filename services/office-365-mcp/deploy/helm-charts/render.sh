#!/bin/bash
# Local helper to quick-render the chart locally to see its output.
# ci-values.yaml supplies the placeholder PUBLIC_BASE_URL, ENTRA_TENANT_ID and ENTRA_CLIENT_ID
# that office-365-mcp.validateValues demands and drops the Postgres connection the values schema demands. CI passes the same
# file, so chart defaults alone never render.
helm template \
    office-365-mcp \
    office-365-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace office-365-mcp \
    --values office-365-mcp/ci-values.yaml
