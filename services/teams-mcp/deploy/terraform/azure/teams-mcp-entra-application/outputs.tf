output "client_id" {
  description = "The application (client) ID. Use this with Tenant ID for authentication."
  value       = azuread_application.teams_mcp.client_id
}

output "client_secrets" {
  description = "Map of client secret IDs and their corresponding Key Vault secret IDs."
  value = {
    for k, v in var.confidential_clients : k => {
      application_password_id = azuread_application_password.client_secret[k].id
      key_vault_secret_id     = azurerm_key_vault_secret.kv_client_secret[k].id
      key_vault_secret_name   = azurerm_key_vault_secret.kv_client_secret[k].name
    }
  }
}
