variable "tools_preset" {
  description = <<-EOT
    Which tools this deployment runs, as a named surface — the pod's TOOLS_PRESET, spelled the same
    way (lowercase only). Set this or tools_enabled, never both, never neither; there is no default.
    Widening a live registration makes every signed-in user meet AADSTS65001 until they sign in
    again, so apply HERE BEFORE the overlay when widening, and AFTER it when narrowing.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.tools_preset == null || contains(keys(local.presets), var.tools_preset)
    error_message = "tools_preset names no surface this connector has. Valid presets: ${join(", ", sort(keys(local.presets)))}."
  }
}

variable "tools_enabled" {
  description = <<-EOT
    Which tools this deployment runs, named individually, for a surface no preset covers — the pod's
    TOOLS_ENABLED, as a list rather than a comma-separated string. `get_me` is always on and need not
    be listed. Order is irrelevant. Set this or tools_preset, never both, never neither.
  EOT
  type        = list(string)
  default     = null

  validation {
    condition     = !(var.tools_preset != null && var.tools_enabled != null)
    error_message = "tools_preset and tools_enabled are alternatives and both are set: remove one. Keep tools_preset for that named surface, or keep tools_enabled to name the tools yourself."
  }

  validation {
    condition     = !(var.tools_preset == null && var.tools_enabled == null)
    error_message = "this registration has no tool surface: set tools_preset to one of ${join(", ", sort(keys(local.presets)))}, or tools_enabled to a list of tool names. There is deliberately no default, because the tools enabled decide which delegated Graph permissions every user of this connector consents to."
  }

  validation {
    condition     = var.tools_enabled == null || length(coalesce(var.tools_enabled, [])) > 0
    error_message = "tools_enabled is set but names no tool. Give it a list of tool names, or set tools_preset to one of: ${join(", ", sort(keys(local.presets)))}."
  }

  validation {
    condition     = var.tools_enabled == null || length(setsubtract(toset(coalesce(var.tools_enabled, [])), toset(local.tool_names))) == 0
    error_message = "tools_enabled names ${join(", ", sort(setsubtract(toset(coalesce(var.tools_enabled, [])), toset(local.tool_names))))}, which this connector has no tool for. The tools it has are: ${join(", ", local.tool_names)}."
  }

  validation {
    condition     = alltrue([for name in coalesce(var.tools_enabled, []) : !strcontains(name, ",")])
    error_message = "tools_enabled is a list of tool names, not the pod's comma-separated TOOLS_ENABLED string. Write [\"list_chats\", \"teams_read_message\"], not [\"list_chats,teams_read_message\"]."
  }
}

variable "display_name" {
  description = <<-EOT
    The display name for the Entra application registration. Two registrations of this service in
    one tenant are normal (one per tool surface), so say which surface this one carries.
  EOT
  type        = string

  validation {
    condition     = length(trimspace(var.display_name)) > 0
    error_message = "display_name must not be empty."
  }
}

variable "notes" {
  description = "Notes for the Entra application, inherited by the service principal unless service_principal_configuration.notes overrides it. Where to write down which cluster consumes this registration."
  type        = string
  default     = null
}

variable "sign_in_audience" {
  description = <<-EOT
    The Microsoft identity platform audiences supported by this application.
    'AzureADMultipleOrgs' is for the customer-tenant flow, where the customer's own administrator
    consents through admin_consent_url rather than through this module's own grant.
  EOT
  type        = string
  default     = "AzureADMyOrg"

  validation {
    condition     = contains(["AzureADMyOrg", "AzureADMultipleOrgs"], var.sign_in_audience)
    error_message = "The sign_in_audience must be one of: 'AzureADMyOrg', or 'AzureADMultipleOrgs'."
  }
}

variable "api_scope_id" {
  description = <<-EOT
    The UUID of the exposed `access_as_user` API scope. Leave null and the module derives it
    deterministically. Set it ONLY to adopt an app registration that already exists, pinning that
    registration's existing UUID: changing it invalidates every token already issued.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.api_scope_id == null || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.api_scope_id))
    error_message = "api_scope_id must be a UUID."
  }
}

variable "secret_name_prefix" {
  description = <<-EOT
    Prefix of the composed Key Vault secret name, `<prefix>-<confidential_clients key>-client-secret`.
    Two registrations of this service in one tenant are normal, and two secrets with the same name in
    the same vault do not conflict at plan time — each apply flips the stored value. Put the axis
    that distinguishes this registration into the suffix (e.g. "office-365-mcp-preview").
  EOT
  type        = string

  validation {
    # Pinned to this service's own name because teams-mcp writes into this same shared vault, so
    # `secret_name_prefix = "teams-mcp"` would plan clean and overwrite its live secret.
    condition     = can(regex("^office-365-mcp(-[a-z0-9]([a-z0-9-]*[a-z0-9])?)?$", var.secret_name_prefix))
    error_message = "secret_name_prefix must be \"office-365-mcp\" or \"office-365-mcp-<suffix>\", lowercase alphanumerics and hyphens. It is pinned to this service's name so a prefix cannot name another service's secrets in a shared Key Vault."
  }

  validation {
    condition = alltrue([
      for key in keys(var.confidential_clients) :
      length("${var.secret_name_prefix}-${key}-client-secret") <= 127
    ])
    error_message = "The composed secret name '<secret_name_prefix>-<key>-client-secret' exceeds Key Vault's 127-character limit for at least one confidential_clients key."
  }
}

variable "confidential_clients" {
  description = <<-EOT
    One entry per environment that signs in through this registration, and at least one: the
    On-Behalf-Of exchange cannot be done without a client secret. One key means one secret, one
    redirect URI derived from its own `public_base_url`, and one set of overlay values.
    The secret is stored in the Key Vault named by client_secret.key_vault_id; the caller owns the
    permissions on that vault and this module outputs the secret ids to grant read on.
    Rotating `rotation_counter` signs every user in again, because the client secret is also the key
    material for this service's OAuth state rows. Zero-downtime rotation is not supported.
  EOT
  type = map(object({
    public_base_url = string
    client_secret = object({
      key_vault_id     = string
      rotation_counter = optional(number, 0)
      end_date         = string
    })
  }))

  validation {
    condition     = length(var.confidential_clients) > 0
    error_message = "confidential_clients must name at least one environment: a registration with no client secret cannot do the On-Behalf-Of exchange, and one with no callback URI refuses every sign-in while applying cleanly."
  }

  validation {
    condition = alltrue([
      for k, v in var.confidential_clients :
      can(regex("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$", v.client_secret.end_date))
    ])
    error_message = "The end_date must be in RFC3339 format (e.g. 2018-01-01T01:02:03Z)."
  }

  validation {
    condition = alltrue([
      for k, v in var.confidential_clients :
      can(regex("^https://[^/?#]+/?$", v.public_base_url))
    ])
    error_message = "Each public_base_url must be an https origin with no path, query or fragment (e.g. https://office-365.mcp.qa.unique.app); the module appends /auth/callback itself."
  }

  validation {
    condition = length(distinct([
      for v in var.confidential_clients : trimsuffix(v.public_base_url, "/")
    ])) == length(var.confidential_clients)
    error_message = "Each confidential_clients entry must have a distinct public_base_url: two keys sharing one base URL register a single callback URI for two secrets, and the sign-ins that work then depend on which apply ran last."
  }

  validation {
    condition = alltrue([
      for k, v in var.confidential_clients :
      can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\\.KeyVault/vaults/[^/]+$", v.client_secret.key_vault_id))
    ])
    error_message = "Each client_secret.key_vault_id must be a Key Vault resource ID (/subscriptions/.../resourceGroups/.../providers/Microsoft.KeyVault/vaults/...), not a vault name or vault URL."
  }
}

variable "extra_redirect_uris" {
  description = "Escape hatch for a redirect URI no confidential_clients entry implies — a local developer loopback, a one-off. Every deployment's own callback is derived from its public_base_url."
  type        = list(string)
  default     = []
}

variable "admin_consent_redirect_uri" {
  description = "Branded landing page, registered as an additional redirect URI and used as the redirect_uri of admin_consent_url, so a completed admin consent lands somewhere that reads like success rather than on an OAuth callback."
  type        = string
  default     = "https://www.unique.ai/setup/consent-completed/entra-id"
}

variable "service_principal_configuration" {
  description = <<-EOT
    `{}` (the default) creates the service principal and grants the resolved delegated permissions
    tenant-wide, on behalf of all users. Set it to null to skip both — for a customer tenant that
    manages its own consent through admin_consent_url or the portal before anyone signs in.
  EOT
  type = object({
    notes = optional(string)
  })
  default = {}
}
