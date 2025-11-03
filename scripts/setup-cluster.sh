#!/bin/bash
# SPDX-SnippetBegin
# SPDX-License-Identifier: Apache License 2.0
# SPDX-SnippetCopyrightText: 2024 © Unique AG
# SPDX-SnippetEnd
echo -e "\n-- Installing necessary CRDs --\n"

# csi-secrets-store-provider-azure can not be tested properly for sscsid-keeper as the underlying Machine Identities are not present and thus the pods fail to start
# helm repo add csi-secrets-store-provider-azure https://azure.github.io/secrets-store-csi-driver-provider-azure/charts
# helm install csi csi-secrets-store-provider-azure/csi-secrets-store-provider-azure

# Install Prometheus Operator CRDs (includes ServiceMonitor, PrometheusRule, etc.)
echo "Installing Prometheus Operator CRDs (monitoring.coreos.com/v1)..."
kubectl apply --server-side -f https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.84.1/stripped-down-crds.yaml

# Get Kubernetes version and extract the major.minor version
version=$(kubectl version -o json | jq -r '.serverVersion.major + "." + .serverVersion.minor' | tr -d '+')
major_version=$(echo $version | cut -d. -f1)
minor_version=$(echo $version | cut -d. -f2)

# Compare version with 1.23. The gateway CRDs use x-kubernetes-validations, which is only supported from 1.23 onwards.
if [ "$major_version" -eq 1 ] && [ "$minor_version" -ge 23 ] || [ "$major_version" -gt 1 ]; then
  echo "Kubernetes version $version >= 1.23, applying Gateway API CRDs"
  kubectl apply -k https://github.com/kubernetes-sigs/gateway-api/config/crd
else
  echo "Kubernetes version $version < 1.23, skipping Gateway API CRDs installation"
  echo "Please use an older version of Gateway API CRDs or upgrade your Kubernetes version"
fi
