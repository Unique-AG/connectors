output "client_id" {
  description = "This ID combined with a Tenant ID will result in a valid workload/managed identity."
  value       = azuread_application.sharepoint_connector.client_id
}
output "object_id" {
  description = "The object ID of the Azure AD service principal. Null if service principal was not created."
  value       = var.service_principal_configuration != null ? azuread_service_principal.sharepoint_connector[0].object_id : null
}

output "admin_consent_url" {
  description = "URL for tenant admins to grant admin consent. Share this with customer tenant admins for multi-tenant scenarios. Requires redirect_uris to be set to avoid AADSTS500113."
  value       = "https://login.microsoftonline.com/organizations/v2.0/adminconsent?client_id=${azuread_application.sharepoint_connector.client_id}&scope=https://graph.microsoft.com/.default${var.admin_consent_redirect_uri != null ? "&redirect_uri=${urlencode(var.admin_consent_redirect_uri)}" : length(var.redirect_uris) > 0 ? "&redirect_uri=${urlencode(var.redirect_uris[0])}" : ""}"
}
