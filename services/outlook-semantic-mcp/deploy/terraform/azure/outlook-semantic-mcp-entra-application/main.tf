data "azuread_application_published_app_ids" "well_known" {}

resource "azuread_service_principal" "msgraph" {
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

locals {
  # Microsoft Graph delegated scopes required by Outlook Semantic MCP
  # Based on SCOPES in services/outlook-semantic-mcp/src/auth/microsoft.provider.ts
  graph_scopes = toset([
    "User.Read",
    "Mail.Read",
    "Mail.ReadBasic",
    "Mail.ReadWrite",
    "MailboxSettings.Read"
  ])
}

resource "azuread_application" "outlook_semantic_mcp" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience
  notes            = var.notes
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

  application_id = azuread_application.outlook_semantic_mcp.id
  display_name   = coalesce(each.value.client_secret.explicit_name, each.key)
  end_date       = each.value.client_secret.end_date

  rotate_when_changed = {
    rotation = each.value.client_secret.rotation_counter
  }
}

resource "azurerm_key_vault_secret" "kv_client_secret" {
  for_each = var.confidential_clients

  name            = coalesce(each.value.client_secret.explicit_name, "${var.client_secrets_prefix}-${each.key}-client-secret")
  value           = azuread_application_password.client_secret[each.key].value
  content_type    = "application/x-ms-client-secret"
  key_vault_id    = each.value.client_secret.key_vault_id
  expiration_date = each.value.client_secret.end_date
}

resource "azuread_service_principal" "outlook_semantic_mcp" {
  count = var.service_principal_configuration != null ? 1 : 0

  client_id    = azuread_application.outlook_semantic_mcp.client_id
  use_existing = true
  notes        = var.service_principal_configuration.notes != null ? var.service_principal_configuration.notes : var.notes
}

resource "time_sleep" "wait_for_graph_propagation" {
  count = var.service_principal_configuration != null ? 1 : 0

  depends_on      = [azuread_application.outlook_semantic_mcp, azuread_service_principal.outlook_semantic_mcp]
  create_duration = "15s"
}

resource "azuread_service_principal_delegated_permission_grant" "outlook_semantic_mcp_graph" {
  count = var.service_principal_configuration != null ? 1 : 0

  service_principal_object_id          = azuread_service_principal.outlook_semantic_mcp[0].object_id
  resource_service_principal_object_id = azuread_service_principal.msgraph.object_id
  claim_values                         = local.graph_scopes

  depends_on = [time_sleep.wait_for_graph_propagation]
}
