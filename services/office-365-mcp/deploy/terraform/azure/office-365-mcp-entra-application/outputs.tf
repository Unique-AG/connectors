output "client_id" {
  description = "The application (client) ID. The pod's ENTRA_CLIENT_ID; use it with the tenant ID for authentication."
  value       = azuread_application.office_365_mcp.client_id
}

output "api_scope" {
  description = "The scope an MCP client requests, api://<client_id>/access_as_user. Published because it is the one value nobody can write down before the application exists, and `auth.py:_REQUIRED_SCOPES` is what rejects a client that asks for anything else."
  value       = local.api_scope
}

output "client_secrets" {
  description = "Map of client secrets and their corresponding Key Vault secrets. Shape kept identical to the sibling MCP modules on purpose, so a caller's Key Vault role assignment and service-account outputs copy across verbatim — a mis-scoped role assignment here is an unreadable secret and a pod that never starts."
  value = {
    for k, v in var.confidential_clients : k => {
      client_secret_end_date                   = azuread_application_password.client_secret[k].end_date
      client_secret_id                         = azuread_application_password.client_secret[k].id
      key_vault_secret_name                    = azurerm_key_vault_secret.kv_client_secret[k].name
      key_vault_secret_resource_versionless_id = azurerm_key_vault_secret.kv_client_secret[k].resource_versionless_id
    }
  }
}

output "service_principal_object_id" {
  description = "The object ID of the service principal, or null when service_principal_configuration is null."
  value       = var.service_principal_configuration != null ? azuread_service_principal.office_365_mcp[0].object_id : null
}

output "admin_consent_url" {
  description = <<-EOT
    URL for a tenant administrator to consent to exactly the permissions this deployment asks for.
    Scope-matched rather than `/.default`: `/.default` consents to whatever the registration happens
    to carry at the time it is clicked, which is not the same sentence as "this selection". The
    server publishes no consent URL at all (see server/manifest.py) because it cannot know that a
    non-callback redirect URI is registered — this module registered it, so it can.
    Single-tenant registrations aim at the tenant itself; AzureADMultipleOrgs aims at
    `organizations`, which is the customer-tenant flow.
    The `+` that `urlencode` writes for the scope separators is replaced with `%20`. Both are correct
    — RFC 6749 serializes query parameters as form-encoded, where `+` IS a space — but no sibling
    module in this repo emits a space-separated scope list (they all send `/.default`), so this
    spelling has no production mileage here and `%20` is unambiguous to a reader and to anything that
    percent-decodes without form-decoding first.
  EOT
  value       = "https://login.microsoftonline.com/${var.sign_in_audience == "AzureADMyOrg" ? data.azuread_client_config.current.tenant_id : "organizations"}/v2.0/adminconsent?client_id=${azuread_application.office_365_mcp.client_id}&scope=${replace(urlencode(join(" ", local.graph_scopes)), "+", "%20")}${var.admin_consent_redirect_uri != null ? "&redirect_uri=${urlencode(var.admin_consent_redirect_uri)}" : ""}"
}

output "tool_surface" {
  description = <<-EOT
    What the selection resolved to: the tools registered, the delegated Graph permissions every user
    of this registration consents to, and the subset an Entra administrator must grant.
    `preset` is null when tools_enabled was used, so a plan diff says what changed in the operator's
    own words. `tools` and `permissions` are in the tool registry's order — which is what makes
    `permissions` diffable, line for line, against GET /manifest on the running pod. That diff is the
    only check that the Terraform here and the Argo overlay in the other repo were set to the same
    selection; nothing inside the server can compare its own ask with this registration.
  EOT
  value = {
    preset        = var.tools_preset
    tools         = local.tools
    permissions   = local.permissions
    graph_scopes  = local.graph_scopes
    admin_consent = local.admin_consent
  }
}

output "deployment_env" {
  description = <<-EOT
    Per confidential-client key, the pod's whole non-secret configuration in the chart's own key
    names. Copy these into the Argo overlay instead of assembling them: PUBLIC_BASE_URL is the same
    string the registered redirect URI was built from, so the two cannot drift, and ENTRA_TENANT_ID
    comes from the provider's own client config so the caller supplies no tenant id.
    TOOLS_ENABLED carries the resolved EXPANSION even when a preset was chosen, and there is
    deliberately no TOOLS_PRESET key: `teams` is derived from the tool registry in the pod as well,
    so an overlay pinned to a preset name widens itself on a chart bump — past a registration nobody
    re-applied — and every sign-in then fails at the authorize hop. The value is pasted as a literal
    string; the chart's schema names that key, which takes it out of additionalProperties and refuses
    the base chart's {value, if} form for it.
    TRAP: ENTRA_TENANT_ID is null under `AzureADMultipleOrgs`, and that is deliberate. The provider's
    client config names the tenant Terraform authenticated against — Unique's — which is the right
    answer only for a single-tenant registration. In the customer-tenant flow the pod must carry the
    CONSENTING tenant's id: `config.py` refuses `common`/`organizations` and AzureProvider derives its
    one expected issuer from this value, so Unique's tenant id here rejects every real token whose
    `iss` names the customer's, logging nothing about the tenant id. Emitting null makes the overlay
    fail on a missing required key instead, which is a question an operator can answer.
  EOT
  value = {
    for key, client in var.confidential_clients : key => {
      PUBLIC_BASE_URL = trimsuffix(client.public_base_url, "/")
      ENTRA_TENANT_ID = var.sign_in_audience == "AzureADMyOrg" ? data.azuread_client_config.current.tenant_id : null
      ENTRA_CLIENT_ID = azuread_application.office_365_mcp.client_id
      TOOLS_ENABLED   = join(",", local.tools)
    }
  }
}
