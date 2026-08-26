data "azuread_client_config" "current" {}

data "azuread_application_published_app_ids" "well_known" {}

# Adopted, not created, only for `oauth2_permission_scope_ids`: it turns a permission name into the
# scope id `required_resource_access` wants, so this module carries no table of Graph UUIDs.
resource "azuread_service_principal" "msgraph" {
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

resource "azuread_application" "office_365_mcp" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience
  notes            = var.notes

  # Two registrations of this service in one tenant are normal (one per tool surface), so a name
  # collision is the same surface applied twice from two states, which overwrite each other's Key
  # Vault secret with a clean plan every time. Guards create only; adopting a registration that
  # already exists needs an import, not an apply.
  prevent_duplicate_names = true

  api {
    # TRAP: the provider defaults this to 1 and forces 2 only for the personal-account audiences
    # this app is not, so nothing stops a v1 registration being created.
    requested_access_token_version = 2

    # The non-OIDC API scope FastMCP's AzureProvider demands: Entra omits OIDC scopes from the `scp`
    # claim, so a custom scope is the only gate on the session token there is. Inline rather than
    # granular because the scope's `value` references nothing of this app's own.
    oauth2_permission_scope {
      # TRAP: changing this expression re-mints the scope id and invalidates every token issued
      # against the old one; an already-applied registration must pin `api_scope_id`.
      id                         = coalesce(var.api_scope_id, uuidv5("url", "api://${var.secret_name_prefix}/${local.api_scope_name}"))
      value                      = local.api_scope_name
      type                       = "User"
      enabled                    = true
      admin_consent_display_name = "Access Office 365 MCP as the signed-in user"
      admin_consent_description  = "Allow an MCP client to call Office 365 MCP on behalf of the signed-in user."
      user_consent_display_name  = "Access Office 365 MCP as you"
      user_consent_description   = "Allow an MCP client to call Office 365 MCP on your behalf."
    }
  }

  required_resource_access {
    resource_app_id = azuread_service_principal.msgraph.client_id

    # `toset` because `resource_access` is a nested list: a set makes the iteration order canonical
    # instead of positional. openid/profile/email/offline_access are deliberately absent — they are
    # consented implicitly and are not delegated permission grants to manage here.
    dynamic "resource_access" {
      for_each = toset(local.permissions)
      content {
        id   = azuread_service_principal.msgraph.oauth2_permission_scope_ids[resource_access.value]
        type = "Scope"
      }
    }
  }

  web {
    redirect_uris = local.redirect_uris

    implicit_grant {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }

  lifecycle {
    # TRAP, mandatory and non-obvious. `identifier_uris` is optional and NOT computed, so without
    # this line this resource asserts "empty" on every apply and deletes what
    # azuread_application_identifier_uri just created. The two resources then fight forever.
    ignore_changes = [identifier_uris]

    # Both read only registry.tf's literal locals, so neither can cycle. The alternative for the
    # first is an `Invalid index` at apply, on a scope id only a live tenant can resolve.
    precondition {
      condition     = length(setsubtract(toset(flatten([for tool in local.tool_registry : tool.permissions])), toset(local.requestable_permissions))) == 0
      error_message = "registry.tf declares ${join(", ", sort(setsubtract(toset(flatten([for tool in local.tool_registry : tool.permissions])), toset(local.requestable_permissions))))}, which is outside REQUESTABLE_PERMISSIONS — almost certainly a misspelling, which every other check in this module would accept."
    }

    precondition {
      condition     = length(setsubtract(toset(local.requestable_permissions), toset(keys(local.needs_admin_consent)))) == 0
      error_message = "needs_admin_consent has no verdict for ${join(", ", sort(setsubtract(toset(local.requestable_permissions), toset(keys(local.needs_admin_consent)))))}, so this module would report that no administrator is needed where one is."
    }
  }
}

# TRAP: forced, not style. The URI must be `api://<this app's own client_id>`, and a resource may
# not refer to itself — `terraform plan` reports `Self-referential block`, `terraform validate` does
# not.
resource "azuread_application_identifier_uri" "api" {
  application_id = azuread_application.office_365_mcp.id
  identifier_uri = local.identifier_uri
}

resource "azuread_application_password" "client_secret" {
  for_each = var.confidential_clients

  application_id = azuread_application.office_365_mcp.id
  display_name   = each.key
  end_date       = each.value.client_secret.end_date

  rotate_when_changed = {
    rotation = each.value.client_secret.rotation_counter
  }
}

resource "azurerm_key_vault_secret" "kv_client_secret" {
  for_each = var.confidential_clients

  # No `explicit_name` escape hatch (teams-mcp has one): it hides which name won when two
  # registrations aim at one shared vault.
  name            = "${var.secret_name_prefix}-${each.key}-client-secret"
  value           = azuread_application_password.client_secret[each.key].value
  content_type    = "application/x-ms-client-secret"
  key_vault_id    = each.value.client_secret.key_vault_id
  expiration_date = each.value.client_secret.end_date
}

resource "azuread_service_principal" "office_365_mcp" {
  count = var.service_principal_configuration != null ? 1 : 0

  client_id    = azuread_application.office_365_mcp.client_id
  use_existing = true
  notes        = var.service_principal_configuration.notes != null ? var.service_principal_configuration.notes : var.notes
}

# Entra needs the application and its principal to be visible to the grant API. Without the wait the
# first apply intermittently fails with a not-found on a principal Terraform has just created.
resource "time_sleep" "wait_for_graph_propagation" {
  count = var.service_principal_configuration != null ? 1 : 0

  depends_on      = [azuread_application.office_365_mcp, azuread_service_principal.office_365_mcp]
  create_duration = "15s"
}

# AllPrincipals — no `user_object_id` — so this is the tenant-wide pre-consent and Terraform is its
# sole writer: a narrowing apply revokes the difference wholesale (README, "Apply order").
resource "azuread_service_principal_delegated_permission_grant" "office_365_mcp_graph" {
  count = var.service_principal_configuration != null ? 1 : 0

  service_principal_object_id          = azuread_service_principal.office_365_mcp[0].object_id
  resource_service_principal_object_id = azuread_service_principal.msgraph.object_id
  claim_values                         = toset(local.permissions)

  depends_on = [time_sleep.wait_for_graph_propagation]
}

# A `check` and not a `precondition`: skipping the grant is a supported state (a customer tenant
# consenting for itself), so refusing it would forbid the case service_principal_configuration =
# null exists for.
check "admin_consent_is_granted_by_somebody" {
  assert {
    condition     = var.service_principal_configuration != null || length(local.admin_consent) == 0
    error_message = "service_principal_configuration is null, so this module grants no consent, and this selection needs an administrator for ${join(", ", local.admin_consent)}. Have the tenant's administrator use the admin_consent_url output (or the portal) before anyone signs in."
  }
}
