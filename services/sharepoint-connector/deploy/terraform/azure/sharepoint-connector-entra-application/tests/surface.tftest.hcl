# The mocks compensate for provider behaviour: a mocked map is EMPTY, so `result["MicrosoftGraph"]`
# fails with `Invalid index`, and every `app_role_ids` lookup this module performs needs an entry.
mock_provider "azuread" {
  override_data {
    target = data.azuread_application_published_app_ids.well_known
    values = {
      result = {
        MicrosoftGraph            = "00000003-0000-0000-c000-000000000000"
        Office365SharePointOnline = "00000003-0000-0ff1-ce00-000000000000"
      }
    }
  }

  override_data {
    target = data.azuread_service_principal.msgraph
    values = {
      client_id = "00000003-0000-0000-c000-000000000000"
      object_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
      app_role_ids = {
        "Sites.Selected"                    = "11111111-1111-1111-1111-111111111111"
        "Lists.SelectedOperations.Selected" = "22222222-2222-2222-2222-222222222222"
        "GroupMember.Read.All"              = "33333333-3333-3333-3333-333333333333"
        "User.ReadBasic.All"                = "44444444-4444-4444-4444-444444444444"
      }
    }
  }

  override_data {
    target = data.azuread_service_principal.sharepoint
    values = {
      client_id = "00000003-0000-0ff1-ce00-000000000000"
      object_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
      app_role_ids = {
        "Sites.Selected" = "55555555-5555-5555-5555-555555555555"
      }
    }
  }

  override_resource {
    target = azuread_application.sharepoint_connector
    values = {
      id        = "/applications/99999999-9999-9999-9999-999999999999"
      client_id = "99999999-9999-9999-9999-999999999999"
    }
  }

  override_resource {
    target = azuread_service_principal.sharepoint_connector
    values = {
      object_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    }
  }
}

mock_provider "time" {}

run "content_and_permissions_grants_both_graph_and_sharepoint_roles" {
  variables {
    sync_mode_role_preset = "content_and_permissions"
  }

  assert {
    condition     = length(azuread_service_principal.sharepoint_connector) == 1
    error_message = "service_principal_configuration defaults to {}, which must create the service principal"
  }

  assert {
    condition     = length(azuread_app_role_assignment.grant_graph_admin_consent) == 4
    error_message = "content_and_permissions must grant the two content-access roles plus GroupMember.Read.All and User.ReadBasic.All, granted ${length(azuread_app_role_assignment.grant_graph_admin_consent)}"
  }

  assert {
    condition     = length(azuread_app_role_assignment.grant_sharepoint_admin_consent) == 1
    error_message = "content_and_permissions must grant the additional SharePoint Online Sites.Selected role, granted ${length(azuread_app_role_assignment.grant_sharepoint_admin_consent)}"
  }

  assert {
    condition     = output.client_id == "99999999-9999-9999-9999-999999999999"
    error_message = "client_id output is ${output.client_id}"
  }

  assert {
    condition     = output.object_id == "cccccccc-cccc-cccc-cccc-cccccccccccc"
    error_message = "object_id output is ${output.object_id}"
  }
}

run "content_only_skips_the_sharepoint_online_grant" {
  variables {
    sync_mode_role_preset = "content_only"
  }

  assert {
    condition     = length(azuread_app_role_assignment.grant_sharepoint_admin_consent) == 0
    error_message = "content_only requests no SharePoint Online role, so this must grant none, granted ${length(azuread_app_role_assignment.grant_sharepoint_admin_consent)}"
  }

  assert {
    condition     = length(azuread_app_role_assignment.grant_graph_admin_consent) == 2
    error_message = "content_only still needs the two content-access Graph roles (Sites.Selected, Lists.SelectedOperations.Selected), granted ${length(azuread_app_role_assignment.grant_graph_admin_consent)}"
  }
}

run "a_null_service_principal_configuration_skips_every_grant" {
  variables {
    service_principal_configuration = null
  }

  assert {
    condition     = length(azuread_service_principal.sharepoint_connector) == 0
    error_message = "service_principal_configuration = null must skip the service principal"
  }

  assert {
    condition     = length(azuread_app_role_assignment.grant_graph_admin_consent) == 0
    error_message = "with no service principal there is nothing to grant a role to"
  }

  assert {
    condition     = output.object_id == null
    error_message = "the object_id output must be null when no service principal is created"
  }
}
