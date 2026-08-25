# `tools/__init__.py:resolve()`, in HCL.
#
# TRAP: every local in this file depends on a variable, so NONE of them may ever be named from a
# `variable ... validation` block — that is a hard `Cycle: local.selected (expand),
# var.tools_enabled (validation)`. Validations may read registry.tf's locals, which reference no
# variable, and nothing from here. The file boundary is the rule.
locals {
  # The two routes in, exactly as resolve() takes them. variables.tf has already refused both-set,
  # neither-set, empty, and unknown names, so there is no fallback here on purpose: a `null`
  # tolerated at this line would be a defaulted tool surface, which is the whole thing the XOR
  # exists to prevent.
  asked_for = var.tools_preset != null ? local.presets[var.tools_preset] : var.tools_enabled

  # resolve()'s `wanted = {ALWAYS_ON, *asked_for}`.
  wanted = concat([local.always_on], local.asked_for)

  # Filtered over the REGISTRY's order, never the caller's, so `tools_enabled = ["read_message",
  # "list_chats"]` and the reverse resolve to one identical list — the same guarantee the pod makes,
  # because the consent screen and every cached On-Behalf-Of token key are keyed by that order.
  selected = [for tool in local.tool_registry : tool if contains(local.wanted, tool.name)]
  tools    = [for tool in local.selected : tool.name]

  # `distinct` keeps first occurrence, which is exactly `dict.fromkeys`. `toset` would sort and lose
  # that order; teams-mcp's `toset()`/`setunion()` shape must NOT be copied here for that reason.
  # Nothing in Entra reads the order — but `tool_surface` publishes it, and that output is what an
  # operator diffs against GET /manifest on the running pod.
  permissions  = distinct(flatten([for tool in local.selected : tool.permissions]))
  graph_scopes = [for permission in local.permissions : "${local.graph_scope_prefix}${permission}"]

  # Indexed rather than looked up with a default, so a permission with no verdict in registry.tf is
  # an `Invalid index` here instead of a silent "no administrator needed" — the same argument
  # `manifest.py:_needs_admin_consent` makes with an assert. main.tf's second precondition is the
  # readable version of the same failure.
  admin_consent = [for permission in local.permissions : permission if local.needs_admin_consent[permission]]

  # The redirect URIs are derived, never supplied. `/auth/callback` is FastMCP's own default path
  # (see registry.tf) and `public_base_url` rides the same `confidential_clients` entry as the
  # secret, so one environment cannot get a secret without getting its callback. `trimsuffix` is
  # what stops a trailing slash producing `//auth/callback`, which Entra matches byte-for-byte and
  # would therefore treat as a different URI.
  redirect_uris = compact(concat(
    [for client in var.confidential_clients : "${trimsuffix(client.public_base_url, "/")}${local.callback_path}"],
    var.extra_redirect_uris,
    [var.admin_consent_redirect_uri],
  ))

  # The Application ID URI, and the scope an MCP client asks for. Both are `api://<this app's own
  # client_id>`, which is why the URI needs its own resource — see the TRAP in main.tf.
  identifier_uri = "api://${azuread_application.office_365_mcp.client_id}"
  api_scope      = "${local.identifier_uri}/${local.api_scope_name}"
}
