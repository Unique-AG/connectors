output "client_id" {
  description = "The application (client) ID. The pod's ENTRA_CLIENT_ID; use it with the tenant ID for authentication."
  value       = azuread_application.office_365_mcp.client_id
}

output "api_scope" {
  description = "The scope an MCP client requests: `api://<client_id>/access_as_user`. A client asking for anything else is refused by the server (`auth.py:_REQUIRED_SCOPES`)."
  value       = local.api_scope
}

output "client_secrets" {
  description = "Map of client secrets and their corresponding Key Vault secrets. Shape matches the sibling MCP modules, so a caller's Key Vault role assignment and service-account wiring copy across unchanged."
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
    Scope-matched rather than `/.default`, which consents to whatever the registration happens to
    carry when it is clicked.
    Scope separators are `%20`, not the `+` that `urlencode` writes — both are RFC-correct, `%20` is
    unambiguous to anything that percent-decodes without form-decoding first.
  EOT
  value       = "https://login.microsoftonline.com/${var.sign_in_audience == "AzureADMyOrg" ? data.azuread_client_config.current.tenant_id : "organizations"}/v2.0/adminconsent?client_id=${azuread_application.office_365_mcp.client_id}&scope=${replace(urlencode(join(" ", local.graph_scopes)), "+", "%20")}${var.admin_consent_redirect_uri != null ? "&redirect_uri=${urlencode(var.admin_consent_redirect_uri)}" : ""}"
}

output "tool_surface" {
  description = <<-EOT
    What the selection resolved to: the tools registered, the delegated Graph permissions every user
    of this registration consents to, and the subset an Entra administrator must grant.
    `tools` and `permissions` are in the tool registry's order, so `permissions` diffs line for line
    against GET /manifest on the running pod (README, "After the first apply").
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
    names. Copy these into the Argo overlay rather than assembling them by hand, so the registered
    redirect URI and the pod's base URL cannot drift.
    TOOLS_ENABLED carries the resolved expansion and there is deliberately no TOOLS_PRESET key: an
    overlay pinned to a preset name widens itself on a chart bump, past a registration nobody
    re-applied (README, "Apply order").
    ENTRA_TENANT_ID is null under `AzureADMultipleOrgs` on purpose: the provider's client config
    names Unique's tenant, but the customer-tenant flow needs the consenting tenant's id, which this
    module cannot know. A missing required key in the overlay is a better failure than a wrong issuer.
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
