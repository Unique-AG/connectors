output "client_id" {
  description = "This ID combined with a Tenant ID will result in a valid workload/managed identity."
  value       = azuread_application.sharepoint_connector.client_id
}
output "object_id" {
  description = "The object ID of the Azure AD service principal. Null if service principal was not created."
  value       = var.service_principal_configuration != null ? azuread_service_principal.sharepoint_connector[0].object_id : null
}
