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

resource "azuread_application_password" "client_secret" {
  for_each = var.confidential_clients

  application_id = azuread_application.teams_mcp.id
  display_name   = coalesce(each.value.client_secret.explicit_name, each.key)
  end_date       = each.value.client_secret.end_date

  rotate_when_changed = {
    rotation = each.value.client_secret.rotation_counter
  }
}

resource "azurerm_key_vault_secret" "kv_client_secret" {
  for_each = var.confidential_clients

  name            = coalesce(each.value.client_secret.explicit_name, each.key)
  value           = azuread_application_password.client_secret[each.key].value
  content_type    = "application/x-ms-client-secret"
  key_vault_id    = each.value.client_secret.key_vault_id
  expiration_date = each.value.client_secret.end_date
}
