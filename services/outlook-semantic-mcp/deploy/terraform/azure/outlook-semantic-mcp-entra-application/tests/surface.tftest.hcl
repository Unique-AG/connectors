# The mocks compensate for provider behaviour: a mocked map is EMPTY, so `result["MicrosoftGraph"]`
# fails with `Invalid index`, and every `oauth2_permission_scope_ids` lookup this module performs
# needs an entry.
mock_provider "azuread" {
  override_data {
    target = data.azuread_application_published_app_ids.well_known
    values = {
      result = { MicrosoftGraph = "00000003-0000-0000-c000-000000000000" }
    }
  }

  override_data {
    target = data.azuread_service_principal.msgraph
    values = {
      client_id = "00000003-0000-0000-c000-000000000000"
      object_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
      oauth2_permission_scope_ids = {
        "User.Read"                  = "11111111-1111-1111-1111-111111111111"
        "User.Read.All"              = "22222222-2222-2222-2222-222222222222"
        "Mail.ReadWrite"             = "33333333-3333-3333-3333-333333333333"
        "Mail.ReadWrite.Shared"      = "44444444-4444-4444-4444-444444444444"
        "MailboxSettings.Read"       = "55555555-5555-5555-5555-555555555555"
        "People.Read"                = "66666666-6666-6666-6666-666666666666"
        "Calendars.ReadWrite.Shared" = "77777777-7777-7777-7777-777777777777"
      }
    }
  }

  override_resource {
    target = azuread_application.outlook_semantic_mcp
    values = {
      id        = "/applications/99999999-9999-9999-9999-999999999999"
      client_id = "99999999-9999-9999-9999-999999999999"
    }
  }

  override_resource {
    target = azuread_service_principal.outlook_semantic_mcp
    values = {
      object_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    }
  }
}

mock_provider "azurerm" {}

mock_provider "time" {}

run "default_variables_grant_the_mail_only_scopes" {
  assert {
    condition     = length(local.graph_scopes) == 6
    error_message = "calendar_integration defaults to disabled, so this should request the six mail scopes, requested ${length(local.graph_scopes)}: ${join(",", local.graph_scopes)}"
  }

  assert {
    condition     = !contains(local.graph_scopes, "Calendars.ReadWrite.Shared")
    error_message = "calendar_integration is disabled by default, so no calendar scope should be requested"
  }

  assert {
    condition     = length(azuread_service_principal.outlook_semantic_mcp) == 1
    error_message = "service_principal_configuration defaults to {}, which must create the service principal"
  }

  assert {
    condition     = output.client_id == "99999999-9999-9999-9999-999999999999"
    error_message = "client_id output is ${output.client_id}"
  }
}

run "calendar_integration_enabled_adds_the_calendar_scope" {
  variables {
    calendar_integration = "enabled"
  }

  assert {
    condition     = length(local.graph_scopes) == 7
    error_message = "calendar_integration enabled should add one scope to the mail-only set, requested ${length(local.graph_scopes)}: ${join(",", local.graph_scopes)}"
  }

  assert {
    condition     = contains(local.graph_scopes, "Calendars.ReadWrite.Shared")
    error_message = "calendar_integration enabled must request Calendars.ReadWrite.Shared"
  }
}

run "a_null_service_principal_configuration_skips_the_grant" {
  variables {
    service_principal_configuration = null
  }

  assert {
    condition     = length(azuread_service_principal.outlook_semantic_mcp) == 0
    error_message = "service_principal_configuration = null must skip the service principal"
  }

  assert {
    condition     = length(azuread_service_principal_delegated_permission_grant.outlook_semantic_mcp_graph) == 0
    error_message = "with no service principal there is nothing to grant the tenant-wide consent to"
  }

  assert {
    condition     = output.service_principal_object_id == null
    error_message = "the service_principal_object_id output must be null when no service principal is created"
  }
}
