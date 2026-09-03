#!/bin/bash
# Local helper to quick-render the chart locally to see its output.
helm template \
    with-intelligence-mcp \
    with-intelligence-mcp \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace with-intelligence-mcp
