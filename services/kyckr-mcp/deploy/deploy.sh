#!/usr/bin/env bash
set -euo pipefail

# Deploys kyckr-mcp to the Unique LAB Azure subscription as an App Service Web App.
# Pattern: ACR (Basic) + B1 App Service Plan + container Web App.
# Disclaimer: LAB is demo-only. No SLA, no client data, no production go-lives.
# Reference: https://unique-ch.atlassian.net/wiki/spaces/DX/pages/1873739786/Labs

# === CONFIGURATION ===
# Unique LAB Azure subscription (see Confluence: Labs page).
SUBSCRIPTION_ID="698f3b43-ccb0-4f97-9e10-2ca89a7782cf"
RG="rg-lab-demo-001-kyckr-mcp"
LOCATION="swedencentral"
APP="kyckr-mcp-app"
ACR="kyckrmcpacr"
KV="kv-kyckr-mcp-lab"
IMAGE="kyckr-mcp:latest"
PORT="9542"

# Key Vault secret names (alphanumeric + hyphens only, no underscores).
KV_SECRET_KYCKR_API_KEY="kyckr-api-key"
KV_SECRET_MCP_API_KEY="mcp-api-key"

# === RESOLVE PATHS ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SERVICE_DIR}/../.." && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.deploy"
DOCKERFILE="services/kyckr-mcp/deploy/Dockerfile"

# === LOAD SECRETS ===
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: ${ENV_FILE} not found." >&2
  echo "Copy .env.deploy.example to .env.deploy and fill in the values." >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

: "${KYCKR_API_KEY:?KYCKR_API_KEY is required in .env.deploy}"
: "${MCP_API_KEY:?MCP_API_KEY is required in .env.deploy}"
: "${KYCKR_API_BASE_URL:=https://test-api.kyckr.com/v2}"

# === PIN SUBSCRIPTION ===
# Switch the active sub explicitly so we never deploy to the wrong place.
az account set --subscription "${SUBSCRIPTION_ID}"
SUBSCRIPTION_NAME="$(az account show --query name -o tsv)"
echo "Deploying to subscription: ${SUBSCRIPTION_NAME} (${SUBSCRIPTION_ID})"
echo "Resource group:            ${RG}"
echo "App name:                  ${APP}"
echo

# === PRE-FLIGHT: RESOURCE GROUP MUST EXIST ===
# The RG is provisioned by the lab Terraform workflow when the corresponding
# entry in environments.yaml is merged to main. We don't create it here.
if ! az group show -n "${RG}" >/dev/null 2>&1; then
  echo "ERROR: Resource group ${RG} not found in subscription ${SUBSCRIPTION_NAME}." >&2
  echo "       The lab RG is provisioned by Terraform when this PR merges to main:" >&2
  echo "       https://github.com/Unique-AG/infrastructure/pull/2565" >&2
  echo "       Check status: gh pr view 2565 --repo Unique-AG/infrastructure" >&2
  exit 1
fi

# === CREATE ACR (persists across deploys) ===
if ! az acr show -n "${ACR}" -g "${RG}" >/dev/null 2>&1; then
  az acr create -n "${ACR}" -g "${RG}" --sku Basic --admin-enabled true
else
  echo "ACR ${ACR} already exists, reusing."
fi

# === BUILD IMAGE IN ACR FROM MONOREPO ROOT ===
# Build context must be the monorepo root so workspace deps (pnpm-workspace.yaml,
# pnpm-lock.yaml, packages/*) are available to the multi-stage build.
echo "Building image in ACR (this can take 5-10 min for first build)..."
(
  cd "${REPO_ROOT}"
  az acr build \
    --registry "${ACR}" \
    --image "${IMAGE}" \
    --file "${DOCKERFILE}" \
    .
)

# === CREATE APP SERVICE PLAN (B1 Linux, ~$13/mo) ===
if ! az appservice plan show -n "${APP}-plan" -g "${RG}" >/dev/null 2>&1; then
  az appservice plan create -n "${APP}-plan" -g "${RG}" --is-linux --sku B1
else
  echo "App Service Plan ${APP}-plan already exists, reusing."
fi

# === CREATE OR UPDATE WEB APP ===
ACR_LOGIN_SERVER="${ACR}.azurecr.io"
ACR_USER="$(az acr credential show -n "${ACR}" --query username -o tsv)"
ACR_PASS="$(az acr credential show -n "${ACR}" --query 'passwords[0].value' -o tsv)"

if ! az webapp show -n "${APP}" -g "${RG}" >/dev/null 2>&1; then
  az webapp create -n "${APP}" -g "${RG}" -p "${APP}-plan" \
    --deployment-container-image-name "${ACR_LOGIN_SERVER}/${IMAGE}"
fi

az webapp config container set -n "${APP}" -g "${RG}" \
  --container-image-name "${ACR_LOGIN_SERVER}/${IMAGE}" \
  --container-registry-url "https://${ACR_LOGIN_SERVER}" \
  --container-registry-user "${ACR_USER}" \
  --container-registry-password "${ACR_PASS}"

# === CREATE KEY VAULT (RBAC mode) ===
if ! az keyvault show -n "${KV}" -g "${RG}" >/dev/null 2>&1; then
  az keyvault create -n "${KV}" -g "${RG}" --location "${LOCATION}" \
    --enable-rbac-authorization true \
    --sku standard >/dev/null
else
  echo "Key Vault ${KV} already exists, reusing."
fi

KV_ID="$(az keyvault show -n "${KV}" -g "${RG}" --query id -o tsv)"

# === GRANT RUNNING USER WRITE ACCESS TO KV ===
# Needed so `az keyvault secret set` below works. Idempotent.
RUNNING_USER_OID="$(az ad signed-in-user show --query id -o tsv)"
az role assignment create \
  --role "Key Vault Secrets Officer" \
  --assignee-object-id "${RUNNING_USER_OID}" \
  --assignee-principal-type User \
  --scope "${KV_ID}" \
  --only-show-errors >/dev/null 2>&1 || true

# === ENABLE WEB APP SYSTEM-ASSIGNED MANAGED IDENTITY ===
WEBAPP_MI_OID="$(az webapp identity assign -n "${APP}" -g "${RG}" --query principalId -o tsv)"

# === GRANT WEB APP MI READ ACCESS TO KV SECRETS ===
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee-object-id "${WEBAPP_MI_OID}" \
  --assignee-principal-type ServicePrincipal \
  --scope "${KV_ID}" \
  --only-show-errors >/dev/null 2>&1 || true

# === WAIT FOR RBAC TO PROPAGATE, THEN SEED SECRETS ===
echo "Seeding Key Vault secrets (waiting for RBAC propagation, up to 90s)..."
for i in 1 2 3 4 5 6 7 8 9; do
  if az keyvault secret set --vault-name "${KV}" --name "${KV_SECRET_KYCKR_API_KEY}" \
       --value "${KYCKR_API_KEY}" --only-show-errors >/dev/null 2>&1; then
    break
  fi
  if [[ $i -eq 9 ]]; then
    echo "ERROR: failed to write secret to Key Vault after 9 tries (~90s)." >&2
    echo "Check: az role assignment list --assignee ${RUNNING_USER_OID} --scope ${KV_ID}" >&2
    exit 1
  fi
  sleep 10
done
az keyvault secret set --vault-name "${KV}" --name "${KV_SECRET_MCP_API_KEY}" \
  --value "${MCP_API_KEY}" --only-show-errors >/dev/null

# === APP SETTINGS (secrets via Key Vault references, non-secrets inline) ===
APP_SETTINGS=(
  "WEBSITES_PORT=${PORT}"
  "PORT=${PORT}"
  "NODE_ENV=production"
  "KYCKR_API_KEY=@Microsoft.KeyVault(VaultName=${KV};SecretName=${KV_SECRET_KYCKR_API_KEY})"
  "MCP_API_KEY=@Microsoft.KeyVault(VaultName=${KV};SecretName=${KV_SECRET_MCP_API_KEY})"
  "KYCKR_API_BASE_URL=${KYCKR_API_BASE_URL}"
)
if [[ -n "${KYCKR_DEFAULT_CUSTOMER_REFERENCE:-}" ]]; then
  APP_SETTINGS+=("KYCKR_DEFAULT_CUSTOMER_REFERENCE=${KYCKR_DEFAULT_CUSTOMER_REFERENCE}")
fi
if [[ -n "${KYCKR_DEFAULT_CONTACT_EMAIL:-}" ]]; then
  APP_SETTINGS+=("KYCKR_DEFAULT_CONTACT_EMAIL=${KYCKR_DEFAULT_CONTACT_EMAIL}")
fi
if [[ -n "${LOG_LEVEL:-}" ]]; then
  APP_SETTINGS+=("LOG_LEVEL=${LOG_LEVEL}")
fi

az webapp config appsettings set -n "${APP}" -g "${RG}" --settings "${APP_SETTINGS[@]}" >/dev/null

# === ALWAYS ON (prevents B1 idle unload) ===
az webapp config set -n "${APP}" -g "${RG}" --always-on true >/dev/null

# === RESTART TO PICK UP NEW IMAGE + SETTINGS ===
az webapp restart -n "${APP}" -g "${RG}" >/dev/null

BASE_URL="https://${APP}.azurewebsites.net"
echo
echo "Done."
echo "  Base URL:        ${BASE_URL}"
echo "  MCP endpoint:    ${BASE_URL}/<MCP_API_KEY>/mcp"
echo
echo "Reveal the key (not printed here to keep it out of terminal scrollback):"
echo "  az keyvault secret show --vault-name ${KV} --name ${KV_SECRET_MCP_API_KEY} --query value -o tsv"
echo
echo "Or read it from your local .env.deploy."
echo
echo "Tail logs with:"
echo "  az webapp log tail -n ${APP} -g ${RG}"
