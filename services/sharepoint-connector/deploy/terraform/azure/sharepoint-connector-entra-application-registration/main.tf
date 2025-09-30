resource "azuread_application" "sharepoint_connector" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience

  required_resource_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000" # Microsoft Graph API

    dynamic "resource_access" {
      for_each = var.required_resource_access
      content {
        id   = resource_access.value.identifier
        type = resource_access.value.type
      }
    }
  }
}

resource "azuread_application_federated_identity_credential" "sharepoint_connector_fic" {
  for_each = var.federated_identity_credentials

  application_id = azuread_application.sharepoint_connector.id
  display_name   = each.key
  description    = each.value.description != null ? each.value.description : each.key
  audiences      = each.value.audiences
  issuer         = each.value.issuer
  subject        = each.value.subject
}
