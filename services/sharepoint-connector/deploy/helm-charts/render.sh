#!/bin/bash
# This is just a local helper to quick-render the chart locally to see its output.
helm template \
    sharepoint-connector \
    sharepoint-connector \
    --api-versions gateway.networking.k8s.io/v1,keda.sh/v1alpha1,monitoring.coreos.com/v1 \
    --namespace chat \
    --set alerts.enabled=true