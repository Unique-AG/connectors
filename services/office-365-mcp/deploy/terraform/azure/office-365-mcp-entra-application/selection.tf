locals {
  preset_names = var.tools_preset == null ? null : [for name in try(tolist(var.tools_preset), split(",", var.tools_preset)) : trimspace(name)]

  asked_for = local.preset_names != null ? distinct(flatten([for name in local.preset_names : local.presets[name]])) : var.tools_enabled

  wanted = concat([local.always_on], local.asked_for)

  selected = [for tool in local.tool_registry : tool if contains(local.wanted, tool.name)]
  tools    = [for tool in local.selected : tool.name]

  permissions  = distinct(flatten([for tool in local.selected : tool.permissions]))
  graph_scopes = [for permission in local.permissions : "${local.graph_scope_prefix}${permission}"]

  admin_consent = [for permission in local.permissions : permission if local.needs_admin_consent[permission]]

  redirect_uris = compact(concat(
    [for client in var.confidential_clients : "${trimsuffix(client.public_base_url, "/")}${local.callback_path}"],
    var.extra_redirect_uris,
    [var.admin_consent_redirect_uri],
  ))

  identifier_uri = "api://${azuread_application.office_365_mcp.client_id}"
  api_scope      = "${local.identifier_uri}/${local.api_scope_name}"
}
