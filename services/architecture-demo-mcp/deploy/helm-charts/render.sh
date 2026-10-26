#!/bin/bash
# mcp-scaffold-commit: 9a91a8864afe, timestamp: 2026-10-21T12:09:32+00:00
# Local helper to quick-render the chart locally to see its output.
helm template \
    architecture-demo-mcp \
    architecture-demo-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace architecture-demo-mcp
