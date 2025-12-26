output "client_id" {
  description = "The application (client) ID. Use this with Tenant ID for authentication."
  value       = azuread_application.teams_mcp.client_id
}

output "application_id" {
  description = "The application ID (object ID in Azure AD). Useful for further configuration."
  value       = azuread_application.teams_mcp.id
}
