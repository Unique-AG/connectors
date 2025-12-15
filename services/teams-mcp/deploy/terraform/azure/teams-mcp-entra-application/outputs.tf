output "client_id" {
  description = "The application (client) ID. Use this with Tenant ID for authentication."
  value       = azuread_application.teams_mcp.client_id
}

output "application_id" {
  description = "The application ID (object ID in Azure AD). Useful for further configuration."
  value       = azuread_application.teams_mcp.id
}

output "object_id" {
  description = "The object ID of the Azure AD service principal. Null if service principal was not created."
  value       = var.service_principal_configuration != null ? azuread_service_principal.teams_mcp[0].object_id : null
}

output "client_secret_id" {
  description = "The key ID of the client secret. Null if client secret was not created."
  value       = var.create_client_secret ? azuread_application_password.teams_mcp_secret[0].key_id : null
  sensitive   = true
}

output "client_secret_value" {
  description = "The value of the client secret. Null if client secret was not created. SENSITIVE - handle with care."
  value       = var.create_client_secret ? azuread_application_password.teams_mcp_secret[0].value : null
  sensitive   = true
}
