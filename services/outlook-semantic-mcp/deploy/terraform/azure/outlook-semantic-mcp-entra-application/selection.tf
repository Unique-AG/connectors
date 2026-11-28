# The permission rule of the service's `resolveScopes`, applied to the locals in
# registry.generated.tf.json. `offline_access` and the OpenID scopes need no registration.
locals {
  tools = (
    var.tools_enabled != null ? var.tools_enabled :
    var.tools_preset != null ? distinct(flatten([for name in var.tools_preset : local.presets[name]])) :
    local.presets["mail"]
  )

  own_permissions = distinct(concat(
    local.base_permissions,
    flatten([for tool in local.tool_registry : tool.permissions if contains(local.tools, tool.name)]),
  ))

  shared_mailboxes = var.delegated_access_scan != "disabled"

  shared_permissions = local.shared_mailboxes ? concat(
    local.shared_mailbox_permissions,
    [for permission in local.own_permissions : local.shared_counterparts[permission] if contains(keys(local.shared_counterparts), permission)],
  ) : []

  requested_permissions = distinct(concat(local.own_permissions, local.shared_permissions))

  replaced_permissions = [for permission in local.requested_permissions : local.replaces[permission] if contains(keys(local.replaces), permission)]

  graph_scopes = toset([for permission in local.requested_permissions : permission if !contains(local.replaced_permissions, permission)])
}
