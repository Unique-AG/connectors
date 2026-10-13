# Runtime settings for the root deployment commands.
AUTH_MODE=fastmcp

validate_deployment() {
  : "${TIINGO_API_KEY:?Set TIINGO_API_KEY in services/tiingo-mcp/.env}"
  AUTH_CONFIGURED=false
  # The Zitadel client needs the callback URL printed by the first deploy, so only the
  # client credentials mark auth as configured; issuer and signing key may be filled in early.
  if [[ -n "${ZITADEL_CLIENT_ID:-}${ZITADEL_CLIENT_SECRET:-}" ]]; then
    validate_auth
    AUTH_CONFIGURED=true
  else
    PROBE_PATH=""
    DEPLOYMENT_NOTE="Existing auth settings are preserved. New apps remain fail-closed until you run ./configure-auth.sh ${APP_PATH}."
  fi
}

configure_deployment() {
  SECRETS+=("tiingo-api-key=${TIINGO_API_KEY}")
  ENV_VARS+=(
    "HOST=0.0.0.0"
    "PYTHON_ENV=production"
    "MCP_AUTH_MODE=zitadel"
    "MCP_BASE_URL=${BASE_URL}"
    "TIINGO_API_KEY=secretref:tiingo-api-key"
  )
  if [[ "${AUTH_CONFIGURED}" == true ]]; then
    add_fastmcp_auth_settings
  fi
}
