#!/bin/bash
# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00
# Local helper to quick-render the chart locally to see its output.
# ci-values.yaml supplies the three mandatory URLs and the Postgres connection, so the chart
# renders.
helm template \
    kyckr-mcp \
    kyckr-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace kyckr-mcp \
    --values kyckr-mcp/ci-values.yaml
