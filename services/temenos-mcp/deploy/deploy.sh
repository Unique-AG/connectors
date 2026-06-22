#!/usr/bin/env bash
set -euo pipefail

# Deploys temenos-mcp to the Unique LAB Azure subscription as an App Service Web App.
# Pattern: ACR (Basic) + B1 App Service Plan + container Web App.
# Disclaimer: LAB is demo-only. No SLA, no client data, no production go-lives.
# Reference: https://unique-ch.atlassian.net/wiki/spaces/DX/pages/1873739786/Labs

# === CONFIGURATION ===
# Unique LAB Azure subscription (see Confluence: Labs page).
SUBSCRIPTION_ID="698f3b43-ccb0-4f97-9e10-2ca89a7782cf"
RG="rg-lab-demo-001-temenos-mcp"
LOCATION="swedencentral"
APP="temenos-mcp-app"
ACR="temenosmcpacr"
KV="kv-temenos-mcp-lab"
IMAGE="temenos-mcp:latest"
PORT="9543"

# Key Vault secret names (alphanumeric + hyphens only, no underscores).
KV_SECRET_TEMENOS_API_KEY="temenos-api-key"
KV_SECRET_MCP_API_KEY="mcp-api-key"

# === RESOLVE PATHS ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SERVICE_DIR}/../.." && pwd)"
ENV_TPL="${SCRIPT_DIR}/.env.deploy.tpl"
ENV_FILE="${SCRIPT_DIR}/.env.deploy"
DOCKERFILE="services/temenos-mcp/deploy/Dockerfile"

# === UNIFIED CLEANUP ===
# Single EXIT trap that handles both the 1Password-injected env tempfile and
# the auto-stash restore. Bash only honors one trap per signal; declaring this
# upfront keeps later sections from clobbering each other.
RESOLVED_ENV=""
STASH_DONE=false
STASH_MSG=""
cleanup() {
  if [[ -n "${RESOLVED_ENV}" && -f "${RESOLVED_ENV}" ]]; then
    rm -f "${RESOLVED_ENV}"
  fi
  if [[ "${STASH_DONE}" == "true" ]]; then
    local ref
    ref="$(git -C "${REPO_ROOT}" stash list | grep -F "${STASH_MSG}" | head -1 | cut -d: -f1)"
    if [[ -n "${ref}" ]]; then
      echo "Restoring packages/utils/package.json from stash ${ref}..."
      git -C "${REPO_ROOT}" stash pop "${ref}" >/dev/null || \
        echo "WARN: could not auto-restore stash ${ref}. Run: git stash list" >&2
    fi
  fi
}
trap cleanup EXIT

# === LOAD SECRETS ===
# Prefer .env.deploy.tpl + 1Password CLI: secret refs in the template are
# resolved at deploy time via `op inject`, so no plaintext secrets ever land
# on disk. Falls back to .env.deploy (the legacy flow) for operators without
# the 1Password CLI signed in.
if [[ -f "${ENV_TPL}" ]] && command -v op >/dev/null 2>&1 && op whoami >/dev/null 2>&1; then
  echo "Resolving secrets from 1Password (op inject ${ENV_TPL##*/})..."
  RESOLVED_ENV="$(mktemp -t temenos-env.XXXXXX)"
  op inject -i "${ENV_TPL}" -o "${RESOLVED_ENV}"
  # shellcheck disable=SC1090
  set -a; source "${RESOLVED_ENV}"; set +a
elif [[ -f "${ENV_FILE}" ]]; then
  echo "Loading secrets from ${ENV_FILE##*/} (1Password CLI not signed in)."
  # shellcheck disable=SC1090
  set -a; source "${ENV_FILE}"; set +a
else
  echo "ERROR: no secrets source found." >&2
  echo "       Option A: sign in to 1Password (op signin) — uses ${ENV_TPL##*/}." >&2
  echo "       Option B: copy ${ENV_TPL##*/} to ${ENV_FILE##*/}, fill values, re-run." >&2
  exit 1
fi

: "${TEMENOS_API_KEY:?TEMENOS_API_KEY missing (check 1Password item / .env.deploy)}"
: "${MCP_API_KEY:?MCP_API_KEY missing (generate via: openssl rand -hex 32)}"
: "${TEMENOS_API_BASE_URL:=https://api.temenos.com/api/v1.0.0}"

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
  echo "       The lab RG is provisioned by Terraform; open a PR in Unique-AG/infrastructure" >&2
  echo "       adding ${RG} to environments.yaml before re-running this script." >&2
  exit 1
fi

# === CREATE ACR (persists across deploys) ===
if ! az acr show -n "${ACR}" -g "${RG}" >/dev/null 2>&1; then
  az acr create -n "${ACR}" -g "${RG}" --sku Basic --admin-enabled true
else
  echo "ACR ${ACR} already exists, reusing."
fi

# === BUILD AND PUSH IMAGE LOCALLY ===
# az acr build is currently blocked in this lab subscription ("failed to
# download context" 3s into the build agent). Until that is fixed, we build
# locally with --platform linux/amd64 and push to ACR.
#
# Once `az acr build` works in this lab again, this whole section can be
# replaced with:
#   (cd "${REPO_ROOT}" && az acr build --registry "${ACR}" \
#      --image "${IMAGE}" --file "${DOCKERFILE}" .)

# Pre-flight: docker daemon must be running.
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running. Start Docker Desktop and re-run." >&2
  exit 1
fi

# Auto-stash the packages/utils/package.json `prepare: tsc` edit if present.
# That hook runs during `pnpm install` in the deps stage and fails because
# tsconfig.json is not yet in scope, breaking every monorepo Dockerfile build.
# The unified `cleanup` trap restores the stash so the working tree is untouched.
if git -C "${REPO_ROOT}" diff -- packages/utils/package.json 2>/dev/null \
     | grep -qE '^\+\s*"prepare":\s*"tsc"'; then
  STASH_MSG="temenos-deploy-auto-stash-$$"
  echo "Auto-stashing packages/utils/package.json (contains build-breaking prepare:tsc)..."
  if git -C "${REPO_ROOT}" stash push -m "${STASH_MSG}" -- packages/utils/package.json >/dev/null; then
    STASH_DONE=true
  else
    echo "ERROR: failed to stash packages/utils/package.json." >&2
    exit 1
  fi
fi

# Log into ACR (uses the active az session, no password prompt).
echo "Logging into ACR ${ACR}..."
az acr login -n "${ACR}" >/dev/null

# Build for linux/amd64 (App Service runs amd64; Apple Silicon needs the flag).
echo "Building image for linux/amd64 (5-15 min, faster with Docker Desktop Rosetta)..."
(
  cd "${REPO_ROOT}"
  DOCKER_BUILDKIT=1 docker build \
    --platform linux/amd64 \
    -t "${ACR}.azurecr.io/${IMAGE}" \
    -f "${DOCKERFILE}" \
    .
)

# Verify architecture before pushing — pushing an arm64 image leaves App
# Service stuck in a crash loop with "no matching manifest for linux/amd64".
ARCH="$(docker inspect "${ACR}.azurecr.io/${IMAGE}" --format '{{.Architecture}}/{{.Os}}')"
if [[ "${ARCH}" != "amd64/linux" ]]; then
  echo "ERROR: Built image is ${ARCH}, expected amd64/linux." >&2
  echo "       App Service requires amd64. Check --platform flag above." >&2
  exit 1
fi
echo "Image architecture verified: ${ARCH}"

# Push.
echo "Pushing image to ACR..."
docker push "${ACR}.azurecr.io/${IMAGE}" >/dev/null
echo "Image pushed."

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
  if az keyvault secret set --vault-name "${KV}" --name "${KV_SECRET_TEMENOS_API_KEY}" \
       --value "${TEMENOS_API_KEY}" --only-show-errors >/dev/null 2>&1; then
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
  "TEMENOS_API_KEY=@Microsoft.KeyVault(VaultName=${KV};SecretName=${KV_SECRET_TEMENOS_API_KEY})"
  "MCP_API_KEY=@Microsoft.KeyVault(VaultName=${KV};SecretName=${KV_SECRET_MCP_API_KEY})"
  "TEMENOS_API_BASE_URL=${TEMENOS_API_BASE_URL}"
)
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
