output "client_id" {
  description = "The application (client) ID. Use this with Tenant ID for authentication."
  value       = azuread_application.teams_mcp.client_id
}

output "client_secrets" {
  description = "Map of client secret and their corresponding Key Vault secrets."
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
  description = "The object ID of the service principal (only created when service_principal_configuration is set)."
  value       = var.service_principal_configuration != null ? azuread_service_principal.teams_mcp[0].object_id : null
}

output "admin_consent_url" {
  description = "URL for tenant admins to grant admin consent. Share this with customer tenant admins for multi-tenant scenarios (only outputted when sign_in_audience is AzureADMultipleOrgs)."
  value       = var.sign_in_audience == "AzureADMultipleOrgs" ? "https://login.microsoftonline.com/organizations/adminconsent?client_id=${azuread_application.teams_mcp.client_id}" : null
}
