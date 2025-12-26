#!/bin/bash
# Local helper to quick-render the chart locally to see its output.
helm template \
    teams-mcp \
    teams-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace teams-mcp
