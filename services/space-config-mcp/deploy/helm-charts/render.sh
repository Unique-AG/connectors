#!/bin/bash
# mcp-scaffold-commit: 5264f9f14505, timestamp: 2026-11-02T00:13:01+00:00
# Local helper to quick-render the chart locally to see its output.
helm template \
    space-config-mcp \
    space-config-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace space-config-mcp
