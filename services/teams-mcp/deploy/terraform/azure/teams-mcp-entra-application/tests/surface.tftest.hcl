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
        "User.Read"                        = "11111111-1111-1111-1111-111111111111"
        "ChannelMessage.Send"              = "22222222-2222-2222-2222-222222222222"
        "ChatMessage.Send"                 = "33333333-3333-3333-3333-333333333333"
        "Chat.ReadBasic"                   = "44444444-4444-4444-4444-444444444444"
        "Chat.Read"                        = "55555555-5555-5555-5555-555555555555"
        "Team.ReadBasic.All"               = "66666666-6666-6666-6666-666666666666"
        "Channel.ReadBasic.All"            = "77777777-7777-7777-7777-777777777777"
        "ChannelMessage.Read.All"          = "88888888-8888-8888-8888-888888888888"
        "OnlineMeetings.Read"              = "a1111111-1111-1111-1111-111111111111"
        "OnlineMeetingRecording.Read.All"  = "a2222222-2222-2222-2222-222222222222"
        "OnlineMeetingTranscript.Read.All" = "a3333333-3333-3333-3333-333333333333"
      }
    }
  }

  override_resource {
    target = azuread_application.teams_mcp
    values = {
      id        = "/applications/99999999-9999-9999-9999-999999999999"
      client_id = "99999999-9999-9999-9999-999999999999"
    }
  }

  override_resource {
    target = azuread_service_principal.teams_mcp
    values = {
      object_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    }
  }
}

mock_provider "azurerm" {}

mock_provider "time" {}

run "default_variables_grant_the_identity_messaging_and_kb_scopes" {
  assert {
    condition     = length(local.graph_scopes) == 11
    error_message = "chat_integration and unique_integration both default to enabled, so this should request identity(1) + messaging(7) + kb(3) scopes, requested ${length(local.graph_scopes)}: ${join(",", local.graph_scopes)}"
  }

  assert {
    condition     = length(azuread_service_principal.teams_mcp) == 1
    error_message = "service_principal_configuration defaults to {}, which must create the service principal"
  }

  assert {
    condition     = output.client_id == "99999999-9999-9999-9999-999999999999"
    error_message = "client_id output is ${output.client_id}"
  }
}

run "chat_integration_disabled_drops_the_messaging_scopes" {
  variables {
    chat_integration = "disabled"
  }

  assert {
    condition     = length(local.graph_scopes) == 4
    error_message = "with messaging dropped this should keep identity(1) + kb(3), requested ${length(local.graph_scopes)}: ${join(",", local.graph_scopes)}"
  }

  assert {
    condition     = !contains(local.graph_scopes, "Chat.Read")
    error_message = "chat_integration disabled must not request the messaging scope Chat.Read"
  }
}

run "unique_integration_disabled_drops_the_kb_scopes" {
  variables {
    unique_integration = "disabled"
  }

  assert {
    condition     = length(local.graph_scopes) == 8
    error_message = "with kb ingestion dropped this should keep identity(1) + messaging(7), requested ${length(local.graph_scopes)}: ${join(",", local.graph_scopes)}"
  }

  assert {
    condition     = !contains(local.graph_scopes, "OnlineMeetings.Read")
    error_message = "unique_integration disabled must not request the kb scope OnlineMeetings.Read"
  }
}

run "a_null_service_principal_configuration_skips_the_grant" {
  variables {
    service_principal_configuration = null
  }

  assert {
    condition     = length(azuread_service_principal.teams_mcp) == 0
    error_message = "service_principal_configuration = null must skip the service principal"
  }

  assert {
    condition     = length(azuread_service_principal_delegated_permission_grant.teams_mcp_graph) == 0
    error_message = "with no service principal there is nothing to grant the tenant-wide consent to"
  }

  assert {
    condition     = output.service_principal_object_id == null
    error_message = "the service_principal_object_id output must be null when no service principal is created"
  }
}
