#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SERVICE_DIR}/../.." && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.deploy"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${SUBSCRIPTION_ID:=698f3b43-ccb0-4f97-9e10-2ca89a7782cf}"
: "${RESOURCE_GROUP:?Set RESOURCE_GROUP in deploy/.env.deploy}"
: "${LOCATION:=swedencentral}"
: "${ACR_NAME:?Set ACR_NAME in deploy/.env.deploy; Azure registry names are globally unique}"
: "${CONTAINER_APP_ENV:=ir-demo-mcp-env}"
: "${CONTAINER_APP_NAME:=ir-demo-mcp}"
: "${IMAGE_TAG:=$(date -u +%Y%m%d%H%M%S)}"

PORT=9542
IMAGE_REPOSITORY="ir-demo-mcp"
IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
DOCKERFILE="services/demo-ir-mcp/deploy/Dockerfile"

az account set --subscription "${SUBSCRIPTION_ID}"
SUBSCRIPTION_NAME="$(az account show --query name -o tsv)"

if ! az group show --name "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "ERROR: Resource group ${RESOURCE_GROUP} does not exist in ${SUBSCRIPTION_NAME}." >&2
  echo "Request the LAB resource group from INFRA before running this script." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running." >&2
  exit 1
fi

az extension add --name containerapp --upgrade --only-show-errors >/dev/null

if ! az acr show --name "${ACR_NAME}" --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  az acr create \
    --name "${ACR_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --sku Basic \
    --admin-enabled true \
    --only-show-errors >/dev/null
fi

az acr update --name "${ACR_NAME}" --admin-enabled true --only-show-errors >/dev/null
LOGIN_SERVER="$(az acr show --name "${ACR_NAME}" --query loginServer -o tsv)"

az acr login --name "${ACR_NAME}" --only-show-errors >/dev/null
(
  cd "${REPO_ROOT}"
  DOCKER_BUILDKIT=1 docker build \
    --platform linux/amd64 \
    --tag "${LOGIN_SERVER}/${IMAGE}" \
    --file "${DOCKERFILE}" \
    .
)

ARCHITECTURE="$(docker inspect "${LOGIN_SERVER}/${IMAGE}" --format '{{.Architecture}}/{{.Os}}')"
if [[ "${ARCHITECTURE}" != "amd64/linux" ]]; then
  echo "ERROR: Built ${ARCHITECTURE}; Azure Container Apps requires amd64/linux." >&2
  exit 1
fi

docker push "${LOGIN_SERVER}/${IMAGE}"

if ! az containerapp env show \
  --name "${CONTAINER_APP_ENV}" \
  --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  az containerapp env create \
    --name "${CONTAINER_APP_ENV}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --only-show-errors >/dev/null
fi

REGISTRY_USERNAME="$(az acr credential show --name "${ACR_NAME}" --query username -o tsv)"
REGISTRY_PASSWORD="$(az acr credential show --name "${ACR_NAME}" --query 'passwords[0].value' -o tsv)"

if az containerapp show \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1; then
  az containerapp registry set \
    --name "${CONTAINER_APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --server "${LOGIN_SERVER}" \
    --username "${REGISTRY_USERNAME}" \
    --password "${REGISTRY_PASSWORD}" \
    --only-show-errors >/dev/null
  az containerapp update \
    --name "${CONTAINER_APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${LOGIN_SERVER}/${IMAGE}" \
    --min-replicas 1 \
    --max-replicas 1 \
    --set-env-vars "PORT=${PORT}" "DEMO_DB_PATH=/tmp/demo-ir-mcp.sqlite" \
    --only-show-errors >/dev/null
  az containerapp ingress enable \
    --name "${CONTAINER_APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --type external \
    --target-port "${PORT}" \
    --transport auto \
    --allow-insecure false \
    --only-show-errors >/dev/null
else
  az containerapp create \
    --name "${CONTAINER_APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --environment "${CONTAINER_APP_ENV}" \
    --image "${LOGIN_SERVER}/${IMAGE}" \
    --registry-server "${LOGIN_SERVER}" \
    --registry-username "${REGISTRY_USERNAME}" \
    --registry-password "${REGISTRY_PASSWORD}" \
    --ingress external \
    --target-port "${PORT}" \
    --transport auto \
    --revisions-mode single \
    --cpu 0.5 \
    --memory 1Gi \
    --min-replicas 1 \
    --max-replicas 1 \
    --env-vars "PORT=${PORT}" "DEMO_DB_PATH=/tmp/demo-ir-mcp.sqlite" \
    --only-show-errors >/dev/null
fi

FQDN="$(az containerapp show \
  --name "${CONTAINER_APP_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query properties.configuration.ingress.fqdn \
  -o tsv)"
BASE_URL="https://${FQDN}"

curl --fail --silent --show-error \
  --retry 12 \
  --retry-delay 5 \
  --retry-all-errors \
  "${BASE_URL}/probe" >/dev/null

echo "Deployment complete."
echo "Frontend: ${BASE_URL}/"
echo "MCP:      ${BASE_URL}/mcp"
echo "Probe:    ${BASE_URL}/probe"
echo "OIDC callback: ${BASE_URL}/.auth/login/zitadel/callback"
echo
echo "Next: create the Zitadel Web Application, add its credentials to deploy/.env.deploy,"
echo "then run ${SCRIPT_DIR}/configure-auth.sh. See deploy/README.md."
