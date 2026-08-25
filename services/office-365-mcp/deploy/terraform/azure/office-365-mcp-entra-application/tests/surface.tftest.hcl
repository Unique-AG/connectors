# Credential-free. `terraform validate` is a weak gate for this module and must not be trusted as
# the only one: it accepts a self-referential `identifier_uris` while silently pruning the edge, and
# it skips validations on defaulted variables — so it passes a configuration with no tool selection
# at all. This file is the gate that catches both.
#
# `services/office-365-mcp/tests/test_terraform_surface.py` checks the expected permission strings
# below against `tools.resolve()` itself, so they cannot quietly go stale: they are a transcription
# here and a derivation there.
#
# Mock recipe, every line of which was found by a failing run rather than guessed:
#   - `override_data` on the published-app-ids data source, because a mocked map is EMPTY and
#     `result["MicrosoftGraph"]` then fails with `Invalid index`;
#   - `override_resource` on the Graph service principal, for `oauth2_permission_scope_ids`;
#   - `override_resource` on `azuread_application`, whose `id` must be the `/applications/<uuid>`
#     form or `azuread_application_identifier_uri` cannot parse it, and whose `client_id` the
#     provider UUID-validates;
#   - `override_resource` on this app's own service principal, for a UUID `object_id`.
#
# TRAP: assert with `join(",", ...)`. `local.permissions` is a `list(string)` and an HCL literal
# `["a", "b"]` is a tuple, so `==` between them never holds — it warns about mismatched types and
# fails without saying why.
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

  # `teams` is derived from the registry in registry.tf exactly as `PRESETS["teams"] = TOOL_NAMES` is
  # in the pod, so this run is also what fails when the two registries differ in length.
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

  # The authorize request's own spelling, asserted in full rather than via the prefix constant. Every
  # other derived value in selection.tf is checked against the server; this interpolation was not, and
  # a corrupted one (a stray slash, a missing prefix) passed both this file and the pytest gate while
  # making `scope=` in admin_consent_url malformed on every permission — the one output whose entire
  # purpose is to be handed to a tenant administrator, and the only consent path there is when
  # `service_principal_configuration` is null. test_terraform_surface.py compares this literal against
  # `[graph_scope(p) for p in resolve(...)]`, so the transcription cannot rot either.
  assert {
    condition     = join(" ", local.graph_scopes) == "https://graph.microsoft.com/User.Read https://graph.microsoft.com/Chat.Read"
    error_message = "the authorize request's spelling is ${join(" ", local.graph_scopes)}"
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

run "the_order_is_the_registrys_and_never_the_callers" {
  variables {
    tools_enabled = ["read_message", "list_chats"]
  }

  assert {
    condition     = join(",", local.tools) == "get_me,list_chats,read_message"
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

  # The callback path is FastMCP's and not a caller's, so this asserts the derivation rather than a
  # value somebody passed in. A registration carrying anything else applies cleanly and then fails
  # every sign-in.
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
    # `teams-chat` and not a wider preset on purpose: `terraform test` escalates a failed `check`
    # assertion to a test FAILURE, where plan and apply only warn. So the run that exercises the
    # count-gated service principal has to be one whose selection needs no administrator — which is
    # also the only shape of this configuration that is safe without a second party consenting.
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
    tools_enabled = ["list_chats,read_message"]
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

# The pin, not just the charset. `teams-mcp` is in the right charset and composes exactly the secret
# name teams-mcp's own module writes into the shared identity vault, so the charset rule alone let a
# clean plan overwrite another service's live client secret.
run "a_secret_name_prefix_naming_another_service_is_refused" {
  command = plan

  variables {
    tools_preset       = "teams-chat"
    secret_name_prefix = "teams-mcp"
  }

  expect_failures = [var.secret_name_prefix]
}

# Two environments cannot share one host: one callback URI for two secrets means the sign-ins that
# work depend on which apply ran last.
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
