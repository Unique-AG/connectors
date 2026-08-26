# `tools/__init__.py:resolve()`, in HCL.
locals {
  # No fallback on purpose: a null tolerated here is a silently defaulted tool surface, which is what
  # the XOR in variables.tf exists to prevent.
  asked_for = var.tools_preset != null ? local.presets[var.tools_preset] : var.tools_enabled

  wanted = concat([local.always_on], local.asked_for)

  selected = [for tool in local.tool_registry : tool if contains(local.wanted, tool.name)]
  tools    = [for tool in local.selected : tool.name]

  # Not `toset` (it sorts) and not teams-mcp's `setunion` shape: `distinct` keeps first occurrence,
  # and `tool_surface` publishes that order for diffing against the pod's GET /manifest.
  permissions  = distinct(flatten([for tool in local.selected : tool.permissions]))
  graph_scopes = [for permission in local.permissions : "${local.graph_scope_prefix}${permission}"]

  # Indexed, not `lookup(..., false)`: a permission with no verdict must fail here rather than read
  # as "no administrator needed".
  admin_consent = [for permission in local.permissions : permission if local.needs_admin_consent[permission]]

  redirect_uris = compact(concat(
    [for client in var.confidential_clients : "${trimsuffix(client.public_base_url, "/")}${local.callback_path}"],
    var.extra_redirect_uris,
    [var.admin_consent_redirect_uri],
  ))

  identifier_uri = "api://${azuread_application.office_365_mcp.client_id}"
  api_scope      = "${local.identifier_uri}/${local.api_scope_name}"
}
