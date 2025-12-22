data "azuread_application_published_app_ids" "well_known" {}

locals {
  # Application ID for Microsoft Graph
  graph_app_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]

  # Microsoft Graph API roles required by Teams MCP
  # Based on SCOPES in services/teams-mcp/src/auth/microsoft.provider.ts
  graph_roles = toset([
    "User.Read.All",                      # (delegated): df021288-bdef-4463-88db-98f22de89214
    "OnlineMeetings.Read.All",            # (delegated): c1684f21-1984-47fa-9d61-2dc8c296bb70
    "OnlineMeetingRecording.Read.All",    # (delegated): 190c2bb6-1fdd-4fec-9aa2-7d571b5e1fe3
    "OnlineMeetingTranscript.Read.All",   # (delegated): 30b87d18-ebb1-45db-97f8-82ccb1f0190c
  ])
}

# Service principal for Microsoft Graph
resource "azuread_service_principal" "msgraph" {
  client_id    = local.graph_app_id
  use_existing = true
}

# Azure AD application for Teams MCP
resource "azuread_application" "teams_mcp" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience
  notes            = var.notes

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

  # Web configuration for OAuth redirect URIs
  web {
    redirect_uris = var.redirect_uris

    implicit_grant {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }
}

# Service principal for the Teams MCP application
resource "azuread_service_principal" "teams_mcp" {
  count = var.service_principal_configuration != null ? 1 : 0

  client_id    = azuread_application.teams_mcp.client_id
  use_existing = true
  notes        = var.service_principal_configuration.notes != null ? var.service_principal_configuration.notes : var.notes
}

# Application password (client secret) for OAuth
resource "azuread_application_password" "teams_mcp_secret" {
  count = var.create_client_secret ? 1 : 0

  application_id = azuread_application.teams_mcp.id
  display_name   = "teams-mcp-client-secret"
  end_date       = var.client_secret_end_date
}
