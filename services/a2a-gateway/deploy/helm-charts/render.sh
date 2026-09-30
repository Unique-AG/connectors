#!/bin/bash
# Local helper to quick-render the chart locally to see its output.
helm template \
    a2a-gateway \
    a2a-gateway \
    --api-versions gateway.networking.k8s.io/v1,monitoring.coreos.com/v1 \
    --namespace a2a-gateway \
    "$@"
