# `terraform validate` skips validations on defaulted variables, so it passes a configuration with
# no tool selection at all; these credential-free runs are the only gate on that.

# The mocks compensate for provider behaviour: a mocked map is EMPTY, so `result["MicrosoftGraph"]`
# fails with `Invalid index`, and `azuread_application.id` must be the `/applications/<uuid>` form
# or `azuread_application_identifier_uri` cannot parse it.
mock_provider "azuread" {
  override_data {
    target = data.azuread_application_published_app_ids.well_known
    values = {
      result = { MicrosoftGraph = "00000003-0000-0000-c000-000000000000" }
    }
  }

  override_resource {
    target = azuread_service_principal.msgraph
    values = {
      client_id = "00000003-0000-0000-c000-000000000000"
      object_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
      oauth2_permission_scope_ids = {
        "User.Read"                        = "11111111-1111-1111-1111-111111111111"
        "Chat.Read"                        = "22222222-2222-2222-2222-222222222222"
        "Team.ReadBasic.All"               = "33333333-3333-3333-3333-333333333333"
        "Channel.ReadBasic.All"            = "44444444-4444-4444-4444-444444444444"
        "ChannelMessage.Read.All"          = "55555555-5555-5555-5555-555555555555"
        "OnlineMeetings.Read"              = "66666666-6666-6666-6666-666666666666"
        "OnlineMeetingTranscript.Read.All" = "77777777-7777-7777-7777-777777777777"
        "OnlineMeetingRecording.Read.All"  = "88888888-8888-8888-8888-888888888888"
      }
    }
  }

  override_resource {
    target = azuread_application.office_365_mcp
    values = {
      id        = "/applications/99999999-9999-9999-9999-999999999999"
      client_id = "99999999-9999-9999-9999-999999999999"
    }
  }

  override_resource {
    target = azuread_service_principal.office_365_mcp
    values = {
      object_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    }
  }
}

mock_provider "azurerm" {}

mock_provider "time" {}

variables {
  display_name       = "Unique AI Office 365 MCP (test)"
  secret_name_prefix = "office-365-mcp-test"
  confidential_clients = {
    unique-qa = {
      public_base_url = "https://office-365.mcp.qa.unique.app"
      client_secret = {
        key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-identity-001/providers/Microsoft.KeyVault/vaults/kv-uq-identity-001"
        end_date     = "2030-01-01T00:00:00Z"
      }
    }
  }
}

run "preset_teams_is_the_whole_surface" {
  variables {
    tools_preset = "teams"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Chat.Read,Team.ReadBasic.All,Channel.ReadBasic.All,ChannelMessage.Read.All,OnlineMeetings.Read,OnlineMeetingTranscript.Read.All,OnlineMeetingRecording.Read.All"
    error_message = "teams composed ${join(",", local.permissions)}"
  }

  assert {
    condition     = length(local.tools) == 10
    error_message = "teams resolved ${length(local.tools)} tools: ${join(",", local.tools)}"
  }

  assert {
    condition     = join(",", local.admin_consent) == "ChannelMessage.Read.All,OnlineMeetingTranscript.Read.All,OnlineMeetingRecording.Read.All"
    error_message = "the widest surface costs an administrator ${join(",", local.admin_consent)}"
  }
}

run "preset_teams_chat_costs_no_administrator" {
  variables {
    tools_preset = "teams-chat"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Chat.Read"
    error_message = "teams-chat composed ${join(",", local.permissions)}"
  }

  assert {
    condition     = length(local.admin_consent) == 0
    error_message = "teams-chat should need no administrator, needs ${join(",", local.admin_consent)}"
  }

  assert {
    condition     = join(" ", local.graph_scopes) == "https://graph.microsoft.com/User.Read https://graph.microsoft.com/Chat.Read"
    error_message = "the authorize request's spelling is ${join(" ", local.graph_scopes)}"
  }

  assert {
    condition     = can(regex("scope=[^&]*%20", output.admin_consent_url)) && !can(regex("scope=[^&]*\\+", output.admin_consent_url))
    error_message = "the scope separators in admin_consent_url are ${output.admin_consent_url}"
  }
}

run "preset_teams_messages" {
  variables {
    tools_preset = "teams-messages"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Chat.Read,ChannelMessage.Read.All"
    error_message = "teams-messages composed ${join(",", local.permissions)}"
  }
}

run "preset_teams_channels" {
  variables {
    tools_preset = "teams-channels"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Team.ReadBasic.All,Channel.ReadBasic.All,ChannelMessage.Read.All"
    error_message = "teams-channels composed ${join(",", local.permissions)}"
  }
}

run "preset_teams_transcripts" {
  variables {
    tools_preset = "teams-transcripts"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Chat.Read,OnlineMeetings.Read,OnlineMeetingTranscript.Read.All"
    error_message = "teams-transcripts composed ${join(",", local.permissions)}"
  }
}

run "preset_teams_recordings" {
  variables {
    tools_preset = "teams-recordings"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Chat.Read,OnlineMeetings.Read,OnlineMeetingRecording.Read.All"
    error_message = "teams-recordings composed ${join(",", local.permissions)}"
  }
}

run "preset_teams_meetings" {
  variables {
    tools_preset = "teams-meetings"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Chat.Read,OnlineMeetings.Read,OnlineMeetingTranscript.Read.All,OnlineMeetingRecording.Read.All"
    error_message = "teams-meetings composed ${join(",", local.permissions)}"
  }
}

run "preset_outlook_read" {
  variables {
    tools_preset = "outlook-read"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Mail.Read,People.Read"
    error_message = "outlook-read composed ${join(",", local.permissions)}"
  }
}

run "preset_outlook_mailbox" {
  variables {
    tools_preset = "outlook-mailbox"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Mail.Read,People.Read,MailboxSettings.Read"
    error_message = "outlook-mailbox composed ${join(",", local.permissions)}"
  }
}

run "preset_outlook_write" {
  variables {
    tools_preset = "outlook-write"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Mail.Read,People.Read,MailboxSettings.Read,Mail.ReadWrite"
    error_message = "outlook-write composed ${join(",", local.permissions)}"
  }
}

run "preset_outlook_send" {
  variables {
    tools_preset = "outlook-send"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Mail.Read,People.Read,MailboxSettings.Read,Mail.ReadWrite,Mail.Send,Mail.ReadBasic"
    error_message = "outlook-send composed ${join(",", local.permissions)}"
  }
}

run "preset_outlook_automate" {
  variables {
    tools_preset = "outlook-automate"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Mail.Read,People.Read,MailboxSettings.Read,Mail.ReadWrite,Mail.Send,Mail.ReadBasic,MailboxSettings.ReadWrite"
    error_message = "outlook-automate composed ${join(",", local.permissions)}"
  }
}

run "the_order_is_the_registrys_and_never_the_callers" {
  variables {
    tools_enabled = ["teams_read_message", "list_chats"]
  }

  assert {
    condition     = join(",", local.tools) == "get_me,list_chats,teams_read_message"
    error_message = "caller order leaked into the tool list: ${join(",", local.tools)}"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Chat.Read,ChannelMessage.Read.All"
    error_message = "caller order leaked into the scope list: ${join(",", local.permissions)}"
  }
}

run "get_me_joins_every_selection" {
  variables {
    tools_enabled = ["list_teams"]
  }

  assert {
    condition     = join(",", local.tools) == "get_me,list_teams"
    error_message = "ALWAYS_ON was not joined: ${join(",", local.tools)}"
  }

  assert {
    condition     = join(",", local.permissions) == "User.Read,Team.ReadBasic.All"
    error_message = "resolved ${join(",", local.permissions)}"
  }
}

run "naming_the_always_on_tool_explicitly_is_accepted" {
  variables {
    tools_enabled = ["get_me", "list_chats"]
  }

  assert {
    condition     = join(",", local.tools) == "get_me,list_chats"
    error_message = "resolved ${join(",", local.tools)}"
  }
}

run "the_registration_is_signable_in_through" {
  variables {
    tools_preset = "teams-chat"
  }

  assert {
    condition     = contains(local.redirect_uris, "https://office-365.mcp.qa.unique.app/auth/callback")
    error_message = "no callback URI was derived: ${join(", ", local.redirect_uris)}"
  }

  assert {
    condition     = local.api_scope == "api://99999999-9999-9999-9999-999999999999/access_as_user"
    error_message = "the API scope is ${local.api_scope}"
  }

  assert {
    condition     = azuread_application_identifier_uri.api.identifier_uri == "api://99999999-9999-9999-9999-999999999999"
    error_message = "the Application ID URI is ${azuread_application_identifier_uri.api.identifier_uri}"
  }

  assert {
    condition     = one(azuread_application.office_365_mcp.api).requested_access_token_version == 2
    error_message = "a v1 access token carries the sts.windows.net issuer, which this service's single-issuer check rejects"
  }
}

run "a_trailing_slash_does_not_produce_a_double_slash" {
  variables {
    tools_preset = "teams-chat"
    confidential_clients = {
      unique-qa = {
        public_base_url = "https://office-365.mcp.qa.unique.app/"
        client_secret = {
          key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-identity-001/providers/Microsoft.KeyVault/vaults/kv-uq-identity-001"
          end_date     = "2030-01-01T00:00:00Z"
        }
      }
    }
  }

  assert {
    condition     = contains(local.redirect_uris, "https://office-365.mcp.qa.unique.app/auth/callback")
    error_message = "Entra matches a redirect URI byte-for-byte, and this registered ${join(", ", local.redirect_uris)}"
  }
}

run "a_customer_tenant_can_own_its_own_consent" {
  variables {
    # `teams-chat` on purpose: `terraform test` escalates a failed `check` assertion to a test
    # FAILURE where plan and apply only warn, so this run's selection must need no administrator.
    tools_preset                    = "teams-chat"
    service_principal_configuration = null
  }

  assert {
    condition     = length(azuread_service_principal.office_365_mcp) == 0
    error_message = "service_principal_configuration = null must skip the service principal and its tenant-wide grant"
  }

  assert {
    condition     = length(azuread_service_principal_delegated_permission_grant.office_365_mcp_graph) == 0
    error_message = "the AllPrincipals grant was created for a tenant that manages its own consent"
  }
}

run "neither_selection_is_refused" {
  command         = plan
  expect_failures = [var.tools_enabled]
}

run "both_selections_are_refused" {
  command = plan

  variables {
    tools_preset  = "teams"
    tools_enabled = ["list_chats"]
  }

  expect_failures = [var.tools_enabled]
}

run "an_empty_selection_is_refused" {
  command = plan

  variables {
    tools_enabled = []
  }

  expect_failures = [var.tools_enabled]
}

run "an_unknown_tool_is_refused" {
  command = plan

  variables {
    tools_enabled = ["list_chats", "read_transcripts"]
  }

  expect_failures = [var.tools_enabled]
}

run "the_comma_separated_env_var_form_is_refused" {
  command = plan

  variables {
    tools_enabled = ["list_chats,teams_read_message"]
  }

  expect_failures = [var.tools_enabled]
}

run "an_unknown_preset_is_refused" {
  command = plan

  variables {
    tools_preset = "outlook"
  }

  expect_failures = [var.tools_preset]
}

run "a_public_base_url_with_a_path_is_refused" {
  command = plan

  variables {
    tools_preset = "teams-chat"
    confidential_clients = {
      unique-qa = {
        public_base_url = "https://office-365.mcp.qa.unique.app/office-365"
        client_secret = {
          key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-identity-001/providers/Microsoft.KeyVault/vaults/kv-uq-identity-001"
          end_date     = "2030-01-01T00:00:00Z"
        }
      }
    }
  }

  expect_failures = [var.confidential_clients]
}

run "a_key_vault_name_instead_of_its_resource_id_is_refused" {
  command = plan

  variables {
    tools_preset = "teams-chat"
    confidential_clients = {
      unique-qa = {
        public_base_url = "https://office-365.mcp.qa.unique.app"
        client_secret = {
          key_vault_id = "kv-uq-identity-001"
          end_date     = "2030-01-01T00:00:00Z"
        }
      }
    }
  }

  expect_failures = [var.confidential_clients]
}

run "an_empty_confidential_clients_map_is_refused" {
  command = plan

  variables {
    tools_preset         = "teams-chat"
    confidential_clients = {}
  }

  expect_failures = [var.confidential_clients]
}

run "an_api_scope_id_that_is_not_a_uuid_is_refused" {
  command = plan

  variables {
    tools_preset = "teams-chat"
    api_scope_id = "access-as-user"
  }

  expect_failures = [var.api_scope_id]
}

run "a_secret_name_prefix_in_the_wrong_charset_is_refused" {
  command = plan

  variables {
    tools_preset       = "teams-chat"
    secret_name_prefix = "Office_365_MCP"
  }

  expect_failures = [var.secret_name_prefix]
}

run "a_secret_name_prefix_naming_another_service_is_refused" {
  command = plan

  variables {
    tools_preset       = "teams-chat"
    secret_name_prefix = "teams-mcp"
  }

  expect_failures = [var.secret_name_prefix]
}

run "two_clients_on_one_base_url_are_refused" {
  command = plan

  variables {
    tools_preset = "teams-chat"
    confidential_clients = {
      one = {
        public_base_url = "https://office-365.mcp.qa.unique.app"
        client_secret = {
          key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv"
          end_date     = "2027-11-14T10:00:00Z"
        }
      }
      two = {
        public_base_url = "https://office-365.mcp.qa.unique.app/"
        client_secret = {
          key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv"
          end_date     = "2027-11-14T10:00:00Z"
        }
      }
    }
  }

  expect_failures = [var.confidential_clients]
}

run "a_composed_secret_name_over_127_characters_is_refused" {
  command = plan

  variables {
    tools_preset = "teams-chat"
    confidential_clients = {
      unique-qa-in-an-environment-whose-name-is-long-enough-to-push-the-composed-secret-name-past-the-limit = {
        public_base_url = "https://office-365.mcp.qa.unique.app"
        client_secret = {
          key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-identity-001/providers/Microsoft.KeyVault/vaults/kv-uq-identity-001"
          end_date     = "2030-01-01T00:00:00Z"
        }
      }
    }
  }

  expect_failures = [var.secret_name_prefix]
}

run "a_blank_display_name_is_refused" {
  command = plan

  variables {
    tools_preset = "teams-chat"
    display_name = " "
  }

  expect_failures = [var.display_name]
}

run "an_end_date_that_is_not_rfc3339_is_refused" {
  command = plan

  variables {
    tools_preset = "teams-chat"
    confidential_clients = {
      unique-qa = {
        public_base_url = "https://office-365.mcp.qa.unique.app"
        client_secret = {
          key_vault_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-identity-001/providers/Microsoft.KeyVault/vaults/kv-uq-identity-001"
          end_date     = "2030-01-01"
        }
      }
    }
  }

  expect_failures = [var.confidential_clients]
}

run "an_unsupported_sign_in_audience_is_refused" {
  command = plan

  variables {
    tools_preset     = "teams-chat"
    sign_in_audience = "AzureADandPersonalMicrosoftAccount"
  }

  expect_failures = [var.sign_in_audience]
}

run "a_single_tenant_registration_emits_a_tenant_id" {
  variables {
    tools_preset = "teams-chat"
  }

  assert {
    condition     = output.deployment_env["unique-qa"].mcpConfig.entra.tenantId != null
    error_message = "the overlay for a single-tenant registration carries no tenant id"
  }
}

run "a_multi_tenant_registration_emits_no_tenant_id" {
  variables {
    tools_preset     = "teams-chat"
    sign_in_audience = "AzureADMultipleOrgs"
  }

  assert {
    condition     = output.deployment_env["unique-qa"].mcpConfig.entra.tenantId == null
    error_message = "the customer-tenant overlay carries ${coalesce(output.deployment_env["unique-qa"].mcpConfig.entra.tenantId, "null")} as its tenant id"
  }
}
