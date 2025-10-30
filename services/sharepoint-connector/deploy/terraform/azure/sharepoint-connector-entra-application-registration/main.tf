data "azuread_application_published_app_ids" "well_known" {}

locals {
  graph_app_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  sharepoint_app_id = data.azuread_application_published_app_ids.well_known.result["Office365SharePointOnline"]
  
  graph_roles = toset(concat(
    var.graph_roles_content, 
    var.roles_mode == "permissions" ? var.graph_roles_permissions : []
  ))
  sharepoint_roles = toset(var.roles_mode == "permissions" ? var.sharepoint_roles_permissions : [])
}

resource "azuread_service_principal" "msgraph" {
  client_id    = local.graph_app_id
  use_existing = true
}

resource "azuread_service_principal" "sharepoint" {
  client_id    = local.sharepoint_app_id
  use_existing = true
}

resource "azuread_application" "sharepoint_connector" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience

  required_resource_access {
    resource_app_id = local.graph_app_id

    dynamic "resource_access" {
      for_each = local.graph_roles
      content {
        id   = azuread_service_principal.msgraph.app_role_ids[resource_access.value]
        type = "Role"
      }
    }
  }

  required_resource_access {
    resource_app_id = local.sharepoint_app_id

    dynamic "resource_access" {
      for_each = local.sharepoint_roles
      content {
        id   = azuread_service_principal.sharepoint.app_role_ids[resource_access.value]
        type = "Role"
      }
    }
  }
}

resource "azuread_service_principal" "sharepoint_connector" {
  client_id    = azuread_application.sharepoint_connector.client_id
  use_existing = true
}

resource "time_sleep" "wait_for_graph_propagation" {
  depends_on      = [azuread_application.sharepoint_connector]
  create_duration = "15s"
}

resource "azuread_app_role_assignment" "grant_graph_admin_consent" {
  for_each            = local.graph_roles
  app_role_id         = azuread_service_principal.msgraph.app_role_ids[each.value]
  principal_object_id = azuread_service_principal.sharepoint_connector.object_id
  resource_object_id  = azuread_service_principal.msgraph.object_id

  depends_on = [time_sleep.wait_for_graph_propagation]
}

resource "azuread_app_role_assignment" "grant_sharepoint_admin_consent" {
  for_each            = local.sharepoint_roles
  app_role_id         = azuread_service_principal.sharepoint.app_role_ids[each.value]
  principal_object_id = azuread_service_principal.sharepoint_connector.object_id
  resource_object_id  = azuread_service_principal.sharepoint.object_id

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
