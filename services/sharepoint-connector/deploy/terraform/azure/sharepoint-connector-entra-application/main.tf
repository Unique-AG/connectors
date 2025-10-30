data "azuread_application_published_app_ids" "well_known" {}

resource "azuread_service_principal" "msgraph" {
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

locals {
  role_presets = {
    content-only = [
      "Files.Read.All",
      "Sites.Selected",
    ]
    content-and-permissions = [
      "Files.Read.All",
      "Group.Read.All",
      "GroupMember.Read.All",
      "Sites.Selected",
      "User.ReadBasic.All"
    ]
  }
  active_role_preset = local.role_presets[var.sync_mode_role_preset]
}

resource "azuread_application" "sharepoint_connector" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience

  required_resource_access {
    resource_app_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]

    dynamic "resource_access" {
      for_each = toset(local.active_role_preset)
      content {
        id   = azuread_service_principal.msgraph.app_role_ids[resource_access.value]
        type = "Role"
      }
    }
  }
}

resource "azuread_service_principal" "sharepoint_connector" {
  count        = var.service_principal_configuration_enabled ? 1 : 0
  client_id    = azuread_application.sharepoint_connector.client_id
  use_existing = true
}

resource "time_sleep" "wait_for_graph_propagation" {
  depends_on      = [azuread_application.sharepoint_connector]
  create_duration = "15s"
}

resource "azuread_app_role_assignment" "grant_admin_consent" {
  for_each            = var.service_principal_configuration_enabled ? toset(local.active_role_preset) : toset([])
  app_role_id         = azuread_service_principal.msgraph.app_role_ids[each.value]
  principal_object_id = azuread_service_principal.sharepoint_connector[0].object_id
  resource_object_id  = azuread_service_principal.msgraph.object_id

  depends_on = [time_sleep.wait_for_graph_propagation]
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

resource "azuread_application_certificate" "sharepoint_connector_certificate" {
  for_each = var.certificates

  application_id = azuread_application.sharepoint_connector.id
  type           = "AsymmetricX509Cert"
  value          = each.value.certificate
  end_date       = each.value.end_date
  start_date     = each.value.start_date
}
