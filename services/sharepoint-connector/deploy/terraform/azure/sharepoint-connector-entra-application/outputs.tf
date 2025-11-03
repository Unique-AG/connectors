output "client_id" {
  description = "This ID combined with a Tenant ID will result in a valid workload/managed identity."
  value       = azuread_application.sharepoint_connector.client_id
}
