data "azuread_application_published_app_ids" "well_known" {}

resource "azuread_service_principal" "msgraph" {
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

locals {
  # Microsoft Graph delegated scopes required by Teams MCP
  # Based on SCOPES in services/teams-mcp/src/auth/microsoft.provider.ts
  graph_scopes = toset([
    "User.Read",
    "OnlineMeetings.Read",
    "OnlineMeetingRecording.Read.All",
    "OnlineMeetingTranscript.Read.All",
  ])
}

# Azure AD application for Teams MCP
resource "azuread_application" "teams_mcp" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience
  notes            = var.notes

  # Microsoft Graph API permissions (delegated)
  required_resource_access {
    resource_app_id = azuread_service_principal.msgraph.client_id

    dynamic "resource_access" {
      for_each = local.graph_scopes
      content {
        id   = azuread_service_principal.msgraph.oauth2_permission_scope_ids[resource_access.value]
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
