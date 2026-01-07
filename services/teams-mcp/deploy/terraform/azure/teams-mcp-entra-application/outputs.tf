output "client_id" {
  description = "The application (client) ID. Use this with Tenant ID for authentication."
  value       = azuread_application.teams_mcp.client_id
}

output "client_secrets" {
  description = "Map of client secret and their corresponding Key Vault secrets."
  value = {
    for k, v in var.confidential_clients : k => {
      client_secret_id       = azuread_application_password.client_secret[k].id
      client_secret_end_date = azuread_application_password.client_secret[k].end_date
      key_vault_secret_id    = azurerm_key_vault_secret.kv_client_secret[k].id
      key_vault_secret_name  = azurerm_key_vault_secret.kv_client_secret[k].name
    }
  }
}
