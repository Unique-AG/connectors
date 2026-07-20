#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.deploy"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: ${ENV_FILE} does not exist." >&2
  echo "Copy .env.deploy.example to .env.deploy and fill in the values." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${SUBSCRIPTION_ID:=698f3b43-ccb0-4f97-9e10-2ca89a7782cf}"
: "${RESOURCE_GROUP:?Set RESOURCE_GROUP in deploy/.env.deploy}"
: "${CONTAINER_APP_NAME:=ir-demo-mcp}"
: "${ZITADEL_ISSUER_URL:?Set ZITADEL_ISSUER_URL in deploy/.env.deploy}"
: "${ZITADEL_CLIENT_ID:?Set ZITADEL_CLIENT_ID in deploy/.env.deploy}"
: "${ZITADEL_CLIENT_SECRET:?Set ZITADEL_CLIENT_SECRET in deploy/.env.deploy}"

PROVIDER_NAME="zitadel"
CLIENT_SECRET_NAME="zitadel-client-key"
OPENID_CONFIGURATION="${ZITADEL_ISSUER_URL%/}/.well-known/openid-configuration"

az account set --subscription "${SUBSCRIPTION_ID}"
az extension add --name containerapp --upgrade --only-show-errors >/dev/null

if ! az containerapp show \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "ERROR: Container App ${CONTAINER_APP_NAME} does not exist in ${RESOURCE_GROUP}." >&2
  echo "Run deploy.sh before configuring authentication." >&2
  exit 1
fi

az containerapp secret set \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --secrets "${CLIENT_SECRET_NAME}=${ZITADEL_CLIENT_SECRET}" \
  --only-show-errors >/dev/null

OIDC_ARGS=(
  --name "${CONTAINER_APP_NAME}"
  --resource-group "${RESOURCE_GROUP}"
  --provider-name "${PROVIDER_NAME}"
  --client-id "${ZITADEL_CLIENT_ID}"
  --client-secret-name "${CLIENT_SECRET_NAME}"
  --openid-configuration "${OPENID_CONFIGURATION}"
  --scopes "openid,profile,email"
  --yes
  --only-show-errors
)

if az containerapp auth openid-connect show \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --provider-name "${PROVIDER_NAME}" >/dev/null 2>&1; then
  az containerapp auth openid-connect update "${OIDC_ARGS[@]}" >/dev/null
else
  az containerapp auth openid-connect add "${OIDC_ARGS[@]}" >/dev/null
fi

az containerapp auth update \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --enabled true \
  --unauthenticated-client-action RedirectToLoginPage \
  --redirect-provider "${PROVIDER_NAME}" \
  --excluded-paths "/mcp,/probe,/manifest" \
  --require-https true \
  --yes \
  --only-show-errors >/dev/null

FQDN="$(az containerapp show \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query properties.configuration.ingress.fqdn \
  -o tsv)"
BASE_URL="https://${FQDN}"

echo "Zitadel authentication configured."
echo "Frontend: ${BASE_URL}/"
echo "API:      ${BASE_URL}/api"
echo "Login:    ${BASE_URL}/.auth/login/${PROVIDER_NAME}?post_login_redirect_uri=/"
echo "MCP:      ${BASE_URL}/mcp (unauthenticated)"
echo "Probe:    ${BASE_URL}/probe (unauthenticated)"
