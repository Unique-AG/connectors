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
        "Mail.Read"                  = "88888888-8888-8888-8888-888888888888"
        "Mail.Read.Shared"           = "99999999-8888-8888-8888-888888888888"
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

run "default_variables_register_the_six_scopes_earlier_versions_did" {
  assert {
    condition     = local.graph_scopes == toset(["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read"])
    error_message = "the default selection (mail tools, shared mailboxes on) must register the six scopes earlier versions did, requested: ${join(",", sort(local.graph_scopes))}"
  }

  assert {
    condition     = toset([for access in one(azuread_application.outlook_semantic_mcp.required_resource_access).resource_access : access.id]) == toset([for scope in ["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read"] : data.azuread_service_principal.msgraph.oauth2_permission_scope_ids[scope]])
    error_message = "the app must register exactly the selected scopes as resource_access"
  }

  assert {
    condition     = toset(azuread_service_principal_delegated_permission_grant.outlook_semantic_mcp_graph[0].claim_values) == toset(["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read"])
    error_message = "the consent grant must hold exactly the selected scopes as claim_values"
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

run "the_mail_and_calendar_tools_add_only_the_calendar_scope" {
  variables {
    tools_preset = ["mail", "calendar"]
  }

  assert {
    condition     = local.graph_scopes == toset(["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read", "Calendars.ReadWrite.Shared"])
    error_message = "the mail and calendar tools must add only Calendars.ReadWrite.Shared to the six mail scopes, requested: ${join(",", sort(local.graph_scopes))}"
  }

  assert {
    condition     = toset([for access in one(azuread_application.outlook_semantic_mcp.required_resource_access).resource_access : access.id]) == toset([for scope in ["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read", "Calendars.ReadWrite.Shared"] : data.azuread_service_principal.msgraph.oauth2_permission_scope_ids[scope]])
    error_message = "the app must register exactly the selected scopes as resource_access"
  }

  assert {
    condition     = toset(azuread_service_principal_delegated_permission_grant.outlook_semantic_mcp_graph[0].claim_values) == toset(["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read", "Calendars.ReadWrite.Shared"])
    error_message = "the consent grant must hold exactly the selected scopes as claim_values"
  }
}

run "the_sync_tools_add_no_scope" {
  variables {
    tools_preset = ["mail", "sync"]
  }

  assert {
    condition     = local.graph_scopes == toset(["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read"])
    error_message = "the sync tools need no permission beyond the mail tools, requested: ${join(",", sort(local.graph_scopes))}"
  }

  assert {
    condition     = toset([for access in one(azuread_application.outlook_semantic_mcp.required_resource_access).resource_access : access.id]) == toset([for scope in ["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read"] : data.azuread_service_principal.msgraph.oauth2_permission_scope_ids[scope]])
    error_message = "the app must register exactly the selected scopes as resource_access"
  }

  assert {
    condition     = toset(azuread_service_principal_delegated_permission_grant.outlook_semantic_mcp_graph[0].claim_values) == toset(["User.Read", "User.Read.All", "Mail.ReadWrite", "Mail.ReadWrite.Shared", "MailboxSettings.Read", "People.Read"])
    error_message = "the consent grant must hold exactly the selected scopes as claim_values"
  }
}

run "the_read_only_selection_registers_only_the_four_read_permissions" {
  variables {
    tools_enabled         = ["search_emails", "fetch_next_search_pages", "open_email", "list_mailboxes_and_directories", "list_categories", "lookup_contacts"]
    delegated_access_scan = "disabled"
  }

  assert {
    condition     = local.graph_scopes == toset(["User.Read", "Mail.Read", "People.Read", "MailboxSettings.Read"])
    error_message = "the read-only selection must register exactly User.Read, Mail.Read, People.Read and MailboxSettings.Read, requested: ${join(",", sort(local.graph_scopes))}"
  }

  assert {
    condition     = toset([for access in one(azuread_application.outlook_semantic_mcp.required_resource_access).resource_access : access.id]) == toset([for scope in ["User.Read", "Mail.Read", "People.Read", "MailboxSettings.Read"] : data.azuread_service_principal.msgraph.oauth2_permission_scope_ids[scope]])
    error_message = "the app must register exactly the selected scopes as resource_access"
  }

  assert {
    condition     = toset(azuread_service_principal_delegated_permission_grant.outlook_semantic_mcp_graph[0].claim_values) == toset(["User.Read", "Mail.Read", "People.Read", "MailboxSettings.Read"])
    error_message = "the consent grant must hold exactly the selected scopes as claim_values"
  }
}

run "read_tools_with_shared_mailboxes_on_register_mail_read_shared" {
  variables {
    tools_enabled = ["search_emails", "open_email"]
  }

  assert {
    condition     = local.graph_scopes == toset(["User.Read", "User.Read.All", "Mail.Read", "Mail.Read.Shared", "MailboxSettings.Read"])
    error_message = "without a draft tool, shared mailboxes add Mail.Read.Shared and User.Read.All, requested: ${join(",", sort(local.graph_scopes))}"
  }

  assert {
    condition     = toset([for access in one(azuread_application.outlook_semantic_mcp.required_resource_access).resource_access : access.id]) == toset([for scope in ["User.Read", "User.Read.All", "Mail.Read", "Mail.Read.Shared", "MailboxSettings.Read"] : data.azuread_service_principal.msgraph.oauth2_permission_scope_ids[scope]])
    error_message = "the app must register exactly the selected scopes as resource_access"
  }

  assert {
    condition     = toset(azuread_service_principal_delegated_permission_grant.outlook_semantic_mcp_graph[0].claim_values) == toset(["User.Read", "User.Read.All", "Mail.Read", "Mail.Read.Shared", "MailboxSettings.Read"])
    error_message = "the consent grant must hold exactly the selected scopes as claim_values"
  }
}

run "an_unknown_tool_is_rejected" {
  command = plan

  variables {
    tools_enabled = ["search_emails", "create_draft_email"]
  }

  expect_failures = [var.tools_enabled]
}

run "an_unknown_group_is_rejected" {
  command = plan

  variables {
    tools_preset = ["mail", "contacts"]
  }

  expect_failures = [var.tools_preset]
}

run "tools_preset_and_tools_enabled_together_are_rejected" {
  command = plan

  variables {
    tools_preset  = ["mail"]
    tools_enabled = ["search_emails"]
  }

  expect_failures = [var.tools_enabled]
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
