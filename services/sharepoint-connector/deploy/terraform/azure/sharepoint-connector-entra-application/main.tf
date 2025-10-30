data "azuread_application_published_app_ids" "well_known" {}

locals {
  # Application IDs for Microsoft services
  graph_app_id      = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  sharepoint_app_id = data.azuread_application_published_app_ids.well_known.result["Office365SharePointOnline"]

  # Define role mappings based on sync mode
  role_mappings = {
    content-only = {
      graph_roles      = ["Files.Read.All", "Sites.Selected"]
      sharepoint_roles = []
    }
    content-and-permissions = {
      graph_roles      = ["Files.Read.All", "Sites.Selected", "Group.Read.All", "GroupMember.Read.All", "User.ReadBasic.All"]
      sharepoint_roles = ["Sites.Selected"]
    }
  }

  # Select roles based on sync mode preset
  selected_roles   = local.role_mappings[var.sync_mode_role_preset]
  graph_roles      = toset(local.selected_roles.graph_roles)
  sharepoint_roles = toset(local.selected_roles.sharepoint_roles)
}

# Service principals for Microsoft services
resource "azuread_service_principal" "msgraph" {
  client_id    = local.graph_app_id
  use_existing = true
}

resource "azuread_service_principal" "sharepoint" {
  client_id    = local.sharepoint_app_id
  use_existing = true
}

# Azure AD application for SharePoint Connector
resource "azuread_application" "sharepoint_connector" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience

  # Microsoft Graph API permissions
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

  # SharePoint API permissions (only when content-and-permissions mode)
  dynamic "required_resource_access" {
    for_each = length(local.sharepoint_roles) > 0 ? [1] : []
    content {
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
}

# Service principal for the SharePoint Connector application
resource "azuread_service_principal" "sharepoint_connector" {
  client_id    = azuread_application.sharepoint_connector.client_id
  use_existing = true
}

# Wait for Azure AD propagation
resource "time_sleep" "wait_for_graph_propagation" {
  depends_on      = [azuread_application.sharepoint_connector]
  create_duration = "15s"
}

# Grant admin consent for Microsoft Graph permissions
resource "azuread_app_role_assignment" "grant_graph_admin_consent" {
  for_each            = local.graph_roles
  app_role_id         = azuread_service_principal.msgraph.app_role_ids[each.value]
  principal_object_id = azuread_service_principal.sharepoint_connector.object_id
  resource_object_id  = azuread_service_principal.msgraph.object_id

  depends_on = [time_sleep.wait_for_graph_propagation]
}

# Grant admin consent for SharePoint permissions
resource "azuread_app_role_assignment" "grant_sharepoint_admin_consent" {
  for_each            = local.sharepoint_roles
  app_role_id         = azuread_service_principal.sharepoint.app_role_ids[each.value]
  principal_object_id = azuread_service_principal.sharepoint_connector.object_id
  resource_object_id  = azuread_service_principal.sharepoint.object_id

  depends_on = [time_sleep.wait_for_graph_propagation]
}

# Federated identity credentials for workload identity
resource "azuread_application_federated_identity_credential" "sharepoint_connector_fic" {
  for_each = var.federated_identity_credentials

  application_id = azuread_application.sharepoint_connector.id
  display_name   = each.key
  description    = coalesce(each.value.description, each.key)
  audiences      = each.value.audiences
  issuer         = each.value.issuer
  subject        = each.value.subject
}
