data "azuread_application_published_app_ids" "well_known" {}

locals {
  # Application ID for Microsoft Graph
  graph_app_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]

  # Microsoft Graph API roles required by Teams MCP
  # Based on SCOPES in services/teams-mcp/src/auth/microsoft.provider.ts
  graph_roles = toset([
    "e1fe6dd8-ba31-4d61-89e7-88639da4683d", # (delegated): User.Read
    "9be106e1-f4e3-4df5-bdff-e4bc531cbe43", # (delegated): OnlineMeetings.Read
    "190c2bb6-1fdd-4fec-9aa2-7d571b5e1fe3", # (delegated): OnlineMeetingRecording.Read.All
    "30b87d18-ebb1-45db-97f8-82ccb1f0190c", # (delegated): OnlineMeetingTranscript.Read.All
  ])
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
        id   = resource_access.value
        type = "Scope"
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

# Application password (client secret) for OAuth
resource "azuread_application_password" "teams_mcp_secret" {
  count = var.create_client_secret ? 1 : 0

  application_id = azuread_application.teams_mcp.id
  display_name   = "teams-mcp-client-secret"
  end_date       = var.client_secret_end_date
}
