#!/bin/bash
# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00
# Local helper to quick-render the chart locally to see its output.
helm template \
    world-check-mcp \
    world-check-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace world-check-mcp
