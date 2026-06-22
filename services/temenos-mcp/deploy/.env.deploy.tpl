# Committed template — no secret values, safe to commit.
#
# Secrets are resolved at deploy time via `op inject`, which substitutes each
# `op://...` reference with its value from 1Password. `deploy.sh` runs this
# automatically when the 1Password CLI is installed; you can also resolve it
# manually for debugging:
#
#   op signin
#   op inject -i deploy/.env.deploy.tpl -o deploy/.env.deploy
#
# Items live in the "role/developer" vault on unique-team.1password.com.

# === 1Password-sourced secrets ===
TEMENOS_API_KEY="op://role/developer/Temenos Sandbox API key/Api Key"

# === Manually-managed secrets ===
# Generate once with: openssl rand -hex 32
# After first deploy this value is stored in Azure Key Vault — rotate there.
MCP_API_KEY=

# === Non-secret config ===
TEMENOS_API_BASE_URL=https://api.temenos.com/api/v1.0.0

# Optional. fatal | error | warn | info | debug | trace | silent
# LOG_LEVEL=info
