data "azuread_client_config" "current" {}

data "azuread_application_published_app_ids" "well_known" {}

# Microsoft Graph's service principal already exists in every tenant; `use_existing` adopts it. This
# is what turns a permission NAME into the scope id `required_resource_access` wants, which is why
# the module never carries a table of Graph permission UUIDs.
resource "azuread_service_principal" "msgraph" {
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

resource "azuread_application" "office_365_mcp" {
  display_name     = var.display_name
  sign_in_audience = var.sign_in_audience
  notes            = var.notes

  # Entra itself permits duplicate display names; this asks the provider to refuse one anyway. Two
  # registrations of this service in one tenant are normal (one per tool surface) and `display_name`
  # is required so that each says which surface it carries — so a name collision here is not a second
  # surface, it is the same surface applied twice from two states, which alternately overwrite each
  # other's Key Vault secret and break each other's sign-ins with a clean plan every time.
  # Limit worth knowing: the provider only checks this at CREATE. Renaming an existing registration
  # onto a name another one already holds is not caught, and adopting a registration that already
  # exists needs an import rather than an apply.
  prevent_duplicate_names = true

  api {
    # TRAP: the provider defaults this to 1, and only *forces* 2 for the personal-account audiences
    # this app is not — so nothing stops a v1 registration being created. A v1 access token's `iss`
    # is `https://sts.windows.net/{tid}/`, while AzureProvider derives the one expected issuer
    # `https://{authority}/{tenant_id}/v2.0` and offers no way to turn the check off. A v1
    # registration therefore rejects every token, naming nothing.
    requested_access_token_version = 2

    # The non-OIDC API scope FastMCP's AzureProvider demands (`auth.py:_REQUIRED_SCOPES`): Entra
    # omits OIDC scopes from the `scp` claim, so a custom scope is the only gate on the session token
    # there is.
    #
    # Inline rather than the granular `azuread_application_permission_scope`, because the scope's
    # `value` references nothing of this app's own and so raises no self-reference. Going granular
    # would cost a second documented `ignore_changes = [api[0].oauth2_permission_scope]` and lose the
    # `enabled` attribute the granular resource does not have.
    oauth2_permission_scope {
      # TRAP: `secret_name_prefix` is in the uuidv5 name, and it is the only thing in it that varies.
      # Derived from a constant alone, every registration of this module in every tenant would expose
      # the identical scope UUID — which is precisely the case the module documents as normal (two
      # tool surfaces, two module blocks). The prefix is already the required distinguishing axis for
      # the Key Vault secret, so reusing it here keeps one answer to "which registration is this".
      # Changing this expression re-mints the scope id, which invalidates every token issued against
      # the old one, so an already-applied registration must pin `api_scope_id` instead.
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

    # `toset` here and in the delegated grant below, and nowhere else. This block is a list nesting,
    # so Terraform would diff on order, and whether Graph preserves the resourceAccess array on
    # read-back is not something this module can rely on; the order carries no meaning to Entra
    # either. The order that matters is `local.permissions`', and it survives in the outputs, which
    # is where an operator compares it with GET /manifest.
    #
    # openid/profile/email/offline_access are deliberately absent: they are consented implicitly and
    # are not delegated permission grants to manage here.
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

    # The two ceilings the application asserts in Python, checked at plan time. Both read only
    # registry.tf's literal locals, so neither can cycle, and both fail before anything is created —
    # which matters because the alternative for the first one is an `Invalid index` at apply, on a
    # scope id that can only be resolved against a live tenant.
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

# TRAP: a separate resource is FORCED here, not a style choice. The Application ID URI must be
# `api://<this app's own client_id>`, which cannot be written on the resource above — a resource may
# not refer to itself. `terraform validate` reports Success on the inline form and silently prunes
# the self-edge; only plan says `Self-referential block`. That is why `terraform test` and not
# `validate` is this module's gate.
#
# TRAP: `application_id` wants the `/applications/{object_id}` resource-ID form — `.id`. Neither
# `.client_id` nor `.object_id` works, and both fail at apply with a segment-parse error rather than
# at validate.
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

  # The composed name is the only name — no `coalesce(explicit_name, ...)` escape hatch, because
  # that is exactly what hides which name won when two registrations aim at one shared vault. See
  # variables.tf on why secret_name_prefix has no default.
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
  # Not `coalesce`: both sides may legitimately be null, and `coalesce(null, null)` is a hard
  # "no non-null, non-empty-string arguments" failure at plan — on the module's own defaults.
  notes = var.service_principal_configuration.notes != null ? var.service_principal_configuration.notes : var.notes
}

# Entra needs the application and its principal to be visible to the grant API. Without the wait the
# first apply intermittently fails with a not-found on a principal Terraform has just created.
resource "time_sleep" "wait_for_graph_propagation" {
  count = var.service_principal_configuration != null ? 1 : 0

  depends_on      = [azuread_application.office_365_mcp, azuread_service_principal.office_365_mcp]
  create_duration = "15s"
}

# AllPrincipals — no `user_object_id` — so this is the tenant-wide pre-consent, and Terraform is its
# sole writer. A narrowing apply therefore REVOKES the difference wholesale, which is why the overlay
# must be narrowed before this is applied and widened after (README, "Apply order").
#
# `claim_values` is set-typed in the provider, so the registry order is not expressible here and is
# not missed; the ordered list is in `output.tool_surface`.
resource "azuread_service_principal_delegated_permission_grant" "office_365_mcp_graph" {
  count = var.service_principal_configuration != null ? 1 : 0

  service_principal_object_id          = azuread_service_principal.office_365_mcp[0].object_id
  resource_service_principal_object_id = azuread_service_principal.msgraph.object_id
  claim_values                         = toset(local.permissions)

  depends_on = [time_sleep.wait_for_graph_propagation]
}

# A warning and not a `precondition`, because skipping the grant is a supported state (a customer
# tenant consenting for itself) and a hard failure would forbid the very case
# service_principal_configuration = null exists for. What is not supported is skipping it and
# assuming sign-in works: an unconsented admin-consent permission fails at the authorize hop with
# "Need admin approval", for every user, with nothing in this service's logs.
#
# Note that `terraform test` escalates a failed `check` assertion to a test failure, where plan and
# apply only warn — which is why tests/surface.tftest.hcl exercises the null case with `teams-chat`.
check "admin_consent_is_granted_by_somebody" {
  assert {
    condition     = var.service_principal_configuration != null || length(local.admin_consent) == 0
    error_message = "service_principal_configuration is null, so this module grants no consent, and this selection needs an administrator for ${join(", ", local.admin_consent)}. Have the tenant's administrator use the admin_consent_url output (or the portal) before anyone signs in."
  }
}
